# Classifies incoming emails by type and urgency

import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.llm.structured_output import generate_structured
from security.sanitizer import clean_single_line, clean_untrusted_text, new_boundary, normalize_address, remove_boundary

from .config import DEFAULT_CONFIG, ClassifierConfig
from .flag_human import apply_rules, code_only_result
from .models import Classification, EmailType, InboundEmail, LLMClassification, SenderKind

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_QUOTED_LINE = re.compile(r"^\s*(?:>|On .{5,160} wrote:\s*$)")
_SENDER_DESCRIPTIONS: dict[SenderKind, str] = {
    "candidate": "a person who has already applied and has a candidate file",
    "employee": "an employee of this company",
    "unknown": "an unknown address that has no candidate file",
}


class CandidateDirectory(Protocol):
    def find_by_email(self, email: str) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class ClassifierDeps:
    llm: Any = None
    candidates: CandidateDirectory | None = None
    detector: Callable[[str], bool] | None = None
    phishing_detector: Callable[[str], Any] | None = None
    config: ClassifierConfig = DEFAULT_CONFIG
    boundary_factory: Callable[[], str] = new_boundary


def _identify_sender(address: str | None, deps: ClassifierDeps) -> tuple[SenderKind, bool]:
    """Work out who sent the email from its address. Nothing in the email's text is used."""
    if address is None:
        return "unknown", False
    domain = address.rsplit("@", 1)[-1]
    if any(domain == item or domain.endswith(f".{item}") for item in deps.config.internal_email_domains):
        return "employee", False
    if deps.candidates is None:
        return "unknown", False
    records = [
        record
        for record in deps.candidates.find_by_email(address)
        if normalize_address(str(record.get("email", ""))) == address
    ]
    if len(records) != 1:
        return "unknown", False
    return "candidate", bool(records[0].get("decisions"))


def _is_suspicious(texts: list[str], deps: ClassifierDeps) -> bool:
    if deps.detector is None:
        return False
    try:
        return any(deps.detector(text) for text in texts)
    except Exception as error:
        logger.warning("classifier detector failed error_type=%s", type(error).__name__)
        return False


def _assess_phishing(text: str, deps: ClassifierDeps) -> Any:
    if deps.phishing_detector is None:
        return None
    try:
        return deps.phishing_detector(text)
    except Exception as error:
        logger.warning("classifier phishing detector failed error_type=%s", type(error).__name__)
        return None


def _without_quoted_history(text: str) -> str:
    kept = [line for line in text.split("\n") if not _QUOTED_LINE.match(line)]
    # An email that is only quoted text keeps it, so the model is not given nothing to read.
    return "\n".join(kept).strip() or text


def partly_read(text: str, max_chars: int) -> bool:
    """True when the model cannot read all of this email's own words, even without its quoted history."""
    return len(text) > max_chars and len(_without_quoted_history(text)) > max_chars


def model_view(text: str, max_chars: int) -> str:
    """What the model reads. A long email loses its quoted history, then keeps its start and end if still too long."""
    if len(text) <= max_chars:
        return text
    text = _without_quoted_history(text)
    if len(text) <= max_chars:
        return text
    head = max_chars * 3 // 5
    return f"{text[:head]}\n\n[... the middle of this long email was left out ...]\n\n{text[head - max_chars:]}"


def build_messages(
    subject: str, body: str, sender_kind: SenderKind, config: ClassifierConfig, boundary: str
) -> tuple[str, str]:
    template = (_PROMPTS_DIR / f"{config.prompt_version}.md").read_text(encoding="utf-8")
    system = template.replace("{{BOUNDARY}}", boundary).replace("{{SENDER}}", _SENDER_DESCRIPTIONS[sender_kind])
    user = "\n".join(
        [
            f"BEGIN_{boundary}",
            f"Subject: {remove_boundary(subject, boundary)}",
            remove_boundary(body, boundary),
            f"END_{boundary}",
            "",
            "Classify this email as one JSON object.",
        ]
    )
    return system, user


def _matches(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(rf"\b(?:{pattern})\b", text, re.I) for pattern in patterns)


def _apply_topic_rules(result: Classification, text: str, config: ClassifierConfig) -> Classification:
    """Send sensitive topics to a person from code, so this does not depend on the model noticing them."""
    if result.type in {EmailType.AUTOMATIC_REPLY, EmailType.UNRELATED} and result.sender_kind == "unknown":
        if result.needs_human or not _matches(config.stranger_request_patterns, text):
            return result
        return result.model_copy(
            update={
                "needs_human": True,
                "urgency": "normal",
                "rules_applied": [*result.rules_applied, "stranger_request"],
            }
        )
    serious = _matches(config.serious_topic_patterns, text)
    if not serious and not _matches(config.human_topic_patterns, text):
        return result
    update: dict[str, object] = {
        "needs_human": True,
        "can_draft": False,
        "rules_applied": [*result.rules_applied, "serious_topic" if serious else "sensitive_topic"],
    }
    if serious and result.sender_kind != "unknown":
        update["urgency"] = "high"
    return result.model_copy(update=update)


def classify_email(email: InboundEmail, deps: ClassifierDeps) -> Classification:
    """Label one email. This never sends or records anything, and any failure goes to a person."""
    config = deps.config
    started = time.monotonic()
    address = normalize_address(email.from_address)
    try:
        sender_kind, has_decision = _identify_sender(address, deps)
    except Exception as error:
        logger.warning("classifier lookup failed error_type=%s", type(error).__name__)
        return code_only_result(email.email_id, EmailType.UNCLASSIFIED, "unknown", "candidate_lookup_unavailable")

    subject = clean_single_line(email.subject, config.max_subject_chars)
    body = clean_untrusted_text(email.body, config.max_scan_chars)
    raw_text = f"{email.subject}\n{email.body}"
    if _is_suspicious([raw_text, f"{subject.text}\n{body.text}"], deps):
        return code_only_result(email.email_id, EmailType.SUSPICIOUS, sender_kind, "injection_suspected")
    phishing = _assess_phishing(f"{raw_text}\n{subject.text}\n{body.text}", deps)
    if phishing is not None and phishing.verdict == "phishing":
        result = code_only_result(email.email_id, EmailType.SUSPICIOUS, sender_kind, "phishing_suspected")
        return result.model_copy(
            update={
                "reason": f"Warning signs of phishing: {', '.join(phishing.signals)}.",
                "rules_applied": [f"phishing:{','.join(phishing.signals)}"],
            }
        )
    if deps.llm is None:
        return code_only_result(email.email_id, EmailType.UNCLASSIFIED, sender_kind, "llm_unavailable")

    view = model_view(body.text, config.max_email_chars)
    system, user = build_messages(subject.text, view, sender_kind, config, deps.boundary_factory())
    try:
        suggestion = generate_structured(
            deps.llm, LLMClassification, system=system, user=user, timeout_s=config.llm_timeout_s
        )
    except Exception as error:
        # Exception text can quote the prompt, so only its type is logged.
        logger.warning("classifier model failed error_type=%s", type(error).__name__)
        return code_only_result(
            email.email_id, EmailType.UNCLASSIFIED, sender_kind, "llm_failed", config.prompt_version
        )

    reason = clean_single_line(suggestion.reason, config.max_reason_chars).text or None
    result = apply_rules(
        suggestion,
        email_id=email.email_id,
        sender_kind=sender_kind,
        has_recorded_decision=has_decision,
        reason=reason,
        prompt_version=config.prompt_version,
    )
    result = _apply_topic_rules(result, f"{subject.text}\n{body.text}", config)
    if phishing is not None and phishing.verdict == "suspicious":
        result = result.model_copy(
            update={
                "needs_human": True,
                "can_draft": False,
                "rules_applied": [*result.rules_applied, f"phishing_signals:{','.join(phishing.signals)}"],
            }
        )
    # A person must read what the model could not, so a partial reading never decides alone.
    if partly_read(body.text, config.max_email_chars):
        result = result.model_copy(
            update={
                "needs_human": True,
                "can_draft": False,
                "rules_applied": [*result.rules_applied, "partly_read"],
            }
        )
    # Hidden text is a warning sign in itself, so a person should look even if the model saw nothing wrong.
    if subject.hidden_removed or body.hidden_removed:
        result = result.model_copy(
            update={
                "needs_human": True,
                "can_draft": False,
                "rules_applied": [*result.rules_applied, "hidden_content_found"],
            }
        )
    logger.info(
        "classifier outcome email_id=%s type=%s urgency=%s needs_human=%s can_draft=%s latency_ms=%s",
        email.email_id,
        result.type.value,
        result.urgency,
        result.needs_human,
        result.can_draft,
        round((time.monotonic() - started) * 1000),
    )
    return result
