# Turns a sanitized resume into sections and a structured profile
"""One structured call to the local model. The resume is fenced as untrusted data.

Whatever goes wrong, the batch continues: the document falls back to sections
found by headings and is marked extraction_failed.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.llm.client import LLMError
from core.llm.structured_output import StructuredOutputError, generate_structured
from security.injection_detector import find_injection_lines, remove_injection_lines
from security.sanitizer import new_boundary, remove_boundary
from services.screener.config import EXTRACT_PROMPT_VERSION, LLM_TIMEOUT_S
from services.screener.models import CandidateProfile, ResumeSection, SectionKind

_PROMPTS_DIR = Path(__file__).with_name("prompts")
_HEADINGS: dict[SectionKind, str] = {
    "summary": r"summary|profile|objective|about me|profil|resume|الملخص",
    "experience": r"(?:work |professional )?experiences?|employment|exp[eé]riences?(?: professionnelles?)?|الخبرة|الخبرات",
    "education": r"education|formations?|التعليم",
    "project": r"projects?|projets?|المشاريع",
    "skills": r"(?:technical )?skills|comp[eé]tences?|المهارات",
    "other": r"certifications?|languages|langues|other|autres",
}
_HEADING_LINES = {
    kind: re.compile(rf"^\s*(?:{pattern})\s*:?\s*$", re.IGNORECASE) for kind, pattern in _HEADINGS.items()
}


class ExtractionOutput(BaseModel):
    sections: list[ResumeSection] = Field(default_factory=list, max_length=30)
    profile: CandidateProfile = Field(default_factory=CandidateProfile)


@dataclass(frozen=True)
class Extraction:
    sections: list[ResumeSection]
    profile: CandidateProfile | None
    extraction_failed: bool


def split_sections(text: str) -> list[ResumeSection]:
    """Sections from headings alone. Text before the first heading is the summary."""
    sections: list[tuple[SectionKind, list[str]]] = [("summary", [])]
    for line in text.splitlines():
        kind = next((k for k, pattern in _HEADING_LINES.items() if pattern.match(line)), None)
        if kind:
            sections.append((kind, []))
        else:
            sections[-1][1].append(line)
    built = [ResumeSection(kind=kind, text="\n".join(lines).strip()) for kind, lines in sections]
    return [section for section in built if section.text]


def clean_profile(profile: CandidateProfile) -> CandidateProfile:
    """Values copied from the resume could still carry an instruction, and they reach the rubric prompt."""
    return profile.model_copy(update={
        "skills": [skill for skill in profile.skills if skill.strip() and not find_injection_lines(skill)],
        "current_title": None if find_injection_lines(profile.current_title or "") else profile.current_title,
    })


def extract_document(
    text: str, llm: Any, *, boundary_factory: Callable[[], str] = new_boundary, timeout_s: float = LLM_TIMEOUT_S
) -> Extraction:
    """`text` must already be visible-only, pseudonymized and free of the flagged lines."""
    fallback = Extraction(split_sections(text), None, True)
    if llm is None:
        return fallback
    boundary = boundary_factory()
    system = (_PROMPTS_DIR / f"{EXTRACT_PROMPT_VERSION}.md").read_text(encoding="utf-8")
    user = f"BEGIN_{boundary}\n{remove_boundary(text, boundary)}\nEND_{boundary}"
    try:
        output = generate_structured(
            llm, ExtractionOutput, system=system.replace("{{BOUNDARY}}", boundary), user=user, timeout_s=timeout_s
        )
    except (LLMError, StructuredOutputError):
        return fallback

    sections = [
        ResumeSection(kind=section.kind, text=remove_injection_lines(section.text).strip())
        for section in output.sections
    ]
    sections = [section for section in sections if section.text]
    # A model that loses the experience block would silently zero that criterion, so keep the original split.
    if not any(s.kind == "experience" for s in sections) and any(s.kind == "experience" for s in fallback.sections):
        sections = fallback.sections
    return Extraction(sections or fallback.sections, clean_profile(output.profile), False)
