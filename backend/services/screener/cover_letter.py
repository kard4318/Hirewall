# Turns a pseudonymized cover letter into a structured profile for the recruiter to read
"""Display only. Nothing here reaches the ranking or the rubric."""
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.llm.client import LLMError
from core.llm.structured_output import StructuredOutputError, generate_structured
from security.injection_detector import find_injection_lines
from security.sanitizer import new_boundary, remove_boundary
from services.screener.config import COVER_LETTER_PROMPT_VERSION, llm_timeout_s
from services.screener.models import CoverLetterProfile

_PROMPTS_DIR = Path(__file__).with_name("prompts")
_TEXT_FIELDS = ("motivation_summary", "availability", "start_date", "desired_duration", "mobility")
_LIST_FIELDS = ("skills_mentioned", "relevant_experiences", "languages")


def _clean(profile: CoverLetterProfile) -> CoverLetterProfile:
    update: dict[str, Any] = {}
    for name in _TEXT_FIELDS:
        value = getattr(profile, name)
        if value and find_injection_lines(value):
            update[name] = None
    for name in _LIST_FIELDS:
        update[name] = [item for item in getattr(profile, name) if not find_injection_lines(item)]
    return profile.model_copy(update=update)


def extract_cover_letter(
    text: str, llm: Any, *, boundary_factory: Callable[[], str] = new_boundary, timeout_s: float | None = None
) -> CoverLetterProfile | None:
    """`text` must already be visible-only, pseudonymized and free of flagged lines. None means the extraction failed."""
    if llm is None:
        return None
    boundary = boundary_factory()
    system = (_PROMPTS_DIR / f"{COVER_LETTER_PROMPT_VERSION}.md").read_text(encoding="utf-8")
    user = f"BEGIN_{boundary}\n{remove_boundary(text, boundary)}\nEND_{boundary}"
    try:
        profile = generate_structured(
            llm, CoverLetterProfile, system=system.replace("{{BOUNDARY}}", boundary), user=user,
            timeout_s=timeout_s or llm_timeout_s(),
        )
    except (LLMError, StructuredOutputError):
        return None
    return _clean(profile)
