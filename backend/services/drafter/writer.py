# Drafts email replies for human review

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any, Protocol

from pydantic import ValidationError

from security.sanitizer import clean_untrusted_text, new_boundary, remove_boundary

from .config import DrafterConfig
from .models import DraftContext, LLMDraft

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_FALLBACKS_DIR = Path(__file__).parent / "fallbacks"

_REPAIR_INSTRUCTION = (
    "\n\nYour previous response did not match the required JSON schema. "
    "Return only one JSON object that matches it, with no extra fields."
)


class LLMClient(Protocol):
    def complete_json(
        self, *, system: str, user: str, json_schema: dict[str, Any], timeout_s: float
    ) -> str | Mapping[str, Any]: ...


class DraftGenerationError(Exception):
    """The LLM failed or kept returning invalid output. Holds no email or draft text."""


def _trusted_lines(value: Any, path: str = "") -> list[str]:
    """Show one `path: value` line per fact, so a model can copy exact paths and readable dates."""
    if isinstance(value, dict):
        return [line for key, item in value.items() for line in _trusted_lines(item, f"{path}.{key}" if path else key)]
    if isinstance(value, list):
        if not value:
            return [f"{path}: (none)"]
        return [line for index, item in enumerate(value) for line in _trusted_lines(item, f"{path}.{index}")]
    if value is None:
        return [f"{path}: (none)"]
    if isinstance(value, datetime):
        return [f"{path}: {value.day} {value:%B %Y} at {value:%H:%M}"]
    text = str(value)
    return [f"{path}: {json.dumps(text, ensure_ascii=False) if chr(10) in text else text}"]


def build_messages(
    context: DraftContext, config: DrafterConfig, boundary: str, feedback: str | None = None
) -> tuple[str, str]:
    template = (_PROMPTS_DIR / f"{config.prompt_version}.md").read_text(encoding="utf-8")
    view = context.trusted_view()
    # Who decided and when is internal, and the model has no reason to tell a candidate.
    view["decisions"] = [
        {key: value for key, value in decision.items() if key in {"type", "details"}} for decision in view["decisions"]
    ]
    trusted = "\n".join(_trusted_lines(view))
    feedback_section = ""
    if feedback:
        cleaned = clean_untrusted_text(feedback, config.max_email_chars).text
        feedback_section = f"\n# Recruiter feedback (trusted)\n\nApply this to the draft:\n{cleaned}\n"

    system = (
        template.replace("{{BOUNDARY}}", boundary)
        .replace("{{TRUSTED_CONTEXT}}", trusted)
        .replace("{{RECRUITER_FEEDBACK}}", feedback_section)
    )

    lines = [f"BEGIN_{boundary}"]
    for message in context.thread:
        lines.append(f"[{message.direction} | {message.sent_at.isoformat()}]")
        lines.append(f"Subject: {remove_boundary(message.subject, boundary)}")
        lines.append(remove_boundary(message.body, boundary))
        lines.append("")
    lines.append(f"END_{boundary}")
    lines.append("")
    lines.append("Draft the reply to the latest message as one JSON object.")
    return system, "\n".join(lines)


def _parse(raw: Any) -> LLMDraft | None:
    try:
        if isinstance(raw, Mapping):
            return LLMDraft.model_validate(raw)
        if isinstance(raw, str):
            return LLMDraft.model_validate_json(raw)
    except (ValidationError, ValueError):
        return None
    return None


def write_draft(
    context: DraftContext,
    llm: LLMClient,
    config: DrafterConfig,
    *,
    feedback: str | None = None,
    boundary_factory: Callable[[], str] = new_boundary,
) -> LLMDraft:
    """Call the LLM, allowing one repair attempt for invalid output."""
    system, user = build_messages(context, config, boundary_factory(), feedback)
    schema = LLMDraft.model_json_schema()
    for prompt in (user, user + _REPAIR_INSTRUCTION):
        try:
            raw = llm.complete_json(
                system=system,
                user=prompt,
                json_schema=schema,
                timeout_s=config.llm_timeout_s,
            )
        except Exception as error:
            # Exception text can quote the prompt, so only its type is kept.
            raise DraftGenerationError(type(error).__name__) from None
        draft = _parse(raw)
        if draft is not None:
            return draft
    raise DraftGenerationError("invalid_output")


def render_fallback(context: DraftContext) -> tuple[str, str]:
    """Return the subject and body of the safe acknowledgement template."""
    template = Template((_FALLBACKS_DIR / "acknowledgement.txt").read_text(encoding="utf-8"))
    body = template.substitute(
        first_name=context.first_name,
        job_title=context.job_title,
        recruiter_signature=context.recruiter_signature,
    ).strip()
    return f"Your application for {context.job_title}", body
