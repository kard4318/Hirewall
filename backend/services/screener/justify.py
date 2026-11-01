# Scores a candidate against a job with the LLM rubric and explains the score
"""The model writes short evidence first, then three integers on anchored scales.

Code computes the criterion as their mean / 10, so the model never gives a total.
The prompt holds the job and the pseudonymized resume only.
"""
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.llm.client import LLMError
from core.llm.structured_output import StructuredOutputError, generate_structured
from security.sanitizer import new_boundary, remove_boundary
from services.screener.config import RUBRIC_PROMPT_VERSION, llm_timeout_s
from services.screener.models import CandidateDocument, CandidateProfile, JobOffer, RubricResult

_PROMPTS_DIR = Path(__file__).with_name("prompts")


class RubricOutput(BaseModel):
    """Field order matters: a small model writes its evidence before committing to a number."""
    model_config = ConfigDict(extra="forbid")

    skills_text: str = Field(max_length=600)
    skills_coverage: int = Field(ge=0, le=10, strict=True)
    experience_text: str = Field(max_length=600)
    related_experience: int = Field(ge=0, le=10, strict=True)
    field_text: str = Field(max_length=600)
    field_closeness: int = Field(ge=0, le=10, strict=True)


def rubric_score(output: RubricOutput) -> float:
    return round((output.skills_coverage + output.related_experience + output.field_closeness) / 3 / 10, 4)


def _resume_text(document: CandidateDocument, profile: CandidateProfile | None) -> str:
    parts = [f"[{section.kind}]\n{section.text}" for section in document.sections]
    if profile and profile.current_title:
        parts.insert(0, f"[current title]\n{profile.current_title}")
    return "\n\n".join(parts)


def build_rubric_messages(
    job: JobOffer, document: CandidateDocument, profile: CandidateProfile | None, boundary: str
) -> tuple[str, str]:
    system = (_PROMPTS_DIR / f"{RUBRIC_PROMPT_VERSION}.md").read_text(encoding="utf-8")
    requirements = "\n".join(f"- ({req.kind}) {req.text}" for req in job.requirements)
    resume = remove_boundary(_resume_text(document, profile), boundary)
    user = f"Job: {job.title}\nRequirements:\n{requirements}\n\nBEGIN_{boundary}\n{resume}\nEND_{boundary}"
    return system.replace("{{BOUNDARY}}", boundary), user


def score_rubric(
    job: JobOffer,
    document: CandidateDocument,
    profile: CandidateProfile | None,
    llm: Any,
    *,
    boundary_factory: Callable[[], str] = new_boundary,
    timeout_s: float | None = None,
) -> RubricResult:
    """Never raises for a model failure: the criterion is then not applied, and the candidate is still ranked."""
    if llm is None:
        return RubricResult(reason_code="llm_unavailable", prompt_version=RUBRIC_PROMPT_VERSION)
    system, user = build_rubric_messages(job, document, profile, boundary_factory())
    try:
        output = generate_structured(llm, RubricOutput, system=system, user=user, timeout_s=timeout_s or llm_timeout_s())
    except LLMError:
        return RubricResult(reason_code="llm_failed", prompt_version=RUBRIC_PROMPT_VERSION)
    except StructuredOutputError:
        return RubricResult(reason_code="invalid_output", prompt_version=RUBRIC_PROMPT_VERSION)
    return RubricResult(
        score=rubric_score(output),
        skills_coverage=output.skills_coverage,
        related_experience=output.related_experience,
        field_closeness=output.field_closeness,
        skills_text=output.skills_text,
        experience_text=output.experience_text,
        field_text=output.field_text,
        prompt_version=RUBRIC_PROMPT_VERSION,
    )
