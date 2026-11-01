# Turns a job offer document into structured details, and derives the scoring requirements in code
"""One structured call to the local model, fenced like a resume. If it fails, HR gets a nearly empty draft to fill in.

Requirements are built by code, never by the model, so they keep the shape the ranking expects.
"""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.llm.client import LLMError
from core.llm.structured_output import StructuredOutputError, generate_structured
from security.injection_detector import find_injection_lines
from security.pii_bias_filter import find_protected_requirements
from security.sanitizer import new_boundary, remove_boundary
from services.screener.config import JOB_EXTRACT_PROMPT_VERSION, llm_timeout_s
from services.screener.models import JobPostingDetails, Requirement

_PROMPTS_DIR = Path(__file__).with_name("prompts")
MAX_REQUIREMENTS = 40
_TEXT_FIELDS = (
    "company", "location", "duration", "start_date", "department", "summary", "education_level",
    "application_deadline",
)
_LIST_FIELDS = ("responsibilities", "required_skills", "preferred_skills", "languages", "benefits")


@dataclass(frozen=True)
class JobExtraction:
    details: JobPostingDetails
    extraction_failed: bool


def guess_title(text: str) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first[:200] or "Untitled offer"


def _years(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def build_requirements(details: JobPostingDetails) -> list[Requirement]:
    """What scoring reads. "At least N years" is the wording parse_required_years understands."""
    lines: list[tuple[str, str]] = []
    if details.min_years_experience:
        lines.append((f"At least {_years(details.min_years_experience)} years of experience", "required"))
    lines += [(f"Experience with {skill.strip()}", "required") for skill in details.required_skills if skill.strip()]
    lines += [(f"Experience with {skill.strip()}", "preferred") for skill in details.preferred_skills if skill.strip()]
    lines += [(line.strip(), "responsibility") for line in details.responsibilities if len(line.strip()) >= 3]

    requirements: dict[str, Requirement] = {}
    for text, kind in lines:
        requirements.setdefault(text.casefold(), Requirement(text=text, kind=kind))
    return list(requirements.values())[:MAX_REQUIREMENTS]


def flagged_requirements(details: JobPostingDetails, source_text: str = "") -> list[str]:
    """Scans the source too: a model could leave out the very line HR most needs to see."""
    lines = [requirement.text for requirement in build_requirements(details)]
    lines += (details.summary or "").splitlines() + [details.education_level or ""]
    return find_protected_requirements([*lines, *source_text.splitlines()])


def _clean(details: JobPostingDetails, fallback_title: str) -> JobPostingDetails:
    """Values copied from the document could still carry an instruction, and a published offer is shown to the public."""
    update: dict[str, Any] = {}
    for name in _TEXT_FIELDS:
        value = getattr(details, name)
        if value and find_injection_lines(value):
            update[name] = None
    for name in _LIST_FIELDS:
        update[name] = [item for item in getattr(details, name) if not find_injection_lines(item)]
    if find_injection_lines(details.title):
        update["title"] = fallback_title
    return details.model_copy(update=update)


def extract_job(
    text: str, llm: Any, *, boundary_factory: Callable[[], str] = new_boundary, timeout_s: float | None = None
) -> JobExtraction:
    """`text` must already be visible-only and free of the flagged lines."""
    title = guess_title(text)
    fallback = JobExtraction(JobPostingDetails(title=title), True)
    if llm is None:
        return fallback
    boundary = boundary_factory()
    system = (_PROMPTS_DIR / f"{JOB_EXTRACT_PROMPT_VERSION}.md").read_text(encoding="utf-8")
    user = f"BEGIN_{boundary}\n{remove_boundary(text, boundary)}\nEND_{boundary}"
    try:
        details = generate_structured(
            llm, JobPostingDetails, system=system.replace("{{BOUNDARY}}", boundary), user=user,
            timeout_s=timeout_s or llm_timeout_s(),
        )
    except (LLMError, StructuredOutputError):
        return fallback
    return JobExtraction(_clean(details, title), False)
