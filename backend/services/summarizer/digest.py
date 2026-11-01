# Builds the daily inbox digest

import hashlib
import json
import logging
import os
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.llm.structured_output import generate_structured
from security.output_validator import output_problems
from security.pii_bias_filter import mask_pii
from security.sanitizer import clean_single_line, clean_untrusted_text, remove_boundary

from .classify import ClassifierDeps, classify_email, model_view, partly_read
from .flag_human import code_only_result
from .models import EmailType, InboundEmail, LLMSummary

logger = logging.getLogger(__name__)

SCOPE_ALL = "all"
PARTLY_READ_PREFIX = "Partly read, so open it: "
_SCOPE = re.compile(r"^(?:all|\d{4}-\d{2}-\d{2})$")
_PROMPTS_DIR = Path(__file__).parent / "prompts"

TYPE_LABELS = {
    "suspicious": "Quarantined",
    "withdrawal": "Withdrawals",
    "decision_or_feedback": "Decisions and feedback",
    "interview_scheduling": "Interview scheduling",
    "compensation": "Pay and contracts",
    "new_application": "New applications",
    "candidate_question": "Candidate questions",
    "document_submission": "Documents",
    "employee_question": "Employee questions",
    "unclassified": "Needs sorting",
    "automatic_reply": "Automatic replies",
    "unrelated": "Unrelated",
}
_URGENCY_RANK = {"high": 0, "normal": 1, "low": 2}
_NO_MODEL_TYPES = {"automatic_reply", "unrelated", "unclassified"}
# Failed results are not cached, so the next run tries again.
_RETRY_REASONS = {"llm_failed", "llm_unavailable", "candidate_lookup_unavailable"}
_RETRY_SOURCES = {"subject_after_failure"}
LABEL_FIELDS = ("type", "urgency", "needs_human", "can_draft", "sender_kind", "rules_applied")
SIGNAL_NAMES = {
    "credential_request": "asks for a login",
    "dangerous_attachment": "dangerous attachment",
    "payment_request": "asks for payment or bank changes",
    "sensitive_data_request": "asks for personal data",
    "too_good_to_be_true": "too good to be true",
    "authority_claim": "claims authority",
    "secrecy_or_unreachable": "asks for secrecy",
    "pretext": "pretext to start a conversation",
    "lure": "lure to click",
    "threat": "threat",
    "urgency": "pressure to act fast",
    "link": "contains a link",
}


def valid_scope(scope: str) -> bool:
    return bool(_SCOPE.match(scope))


class DigestStore:
    """Local files holding digests and per-email results, so repeat runs do not call the model again."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _write(self, path: Path, data: Any) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(path)

    def _digest_path(self, scope: str) -> Path:
        if not valid_scope(scope):
            raise ValueError("invalid_digest_scope")
        return self._directory / f"digest-{scope}.json"

    def save(self, scope: str, record: dict[str, Any]) -> None:
        self._write(self._digest_path(scope), record)

    def load(self, scope: str) -> dict[str, Any] | None:
        path = self._digest_path(scope)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def saved_scopes(self) -> list[str]:
        """The periods that have a saved digest, most recently generated first."""
        paths = sorted(self._directory.glob("digest-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        scopes = [path.stem.removeprefix("digest-") for path in paths]
        return [scope for scope in scopes if valid_scope(scope)]

    def load_cache(self) -> dict[str, Any]:
        path = self._directory / "email-cache.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def save_cache(self, cache: dict[str, Any]) -> None:
        self._write(self._directory / "email-cache.json", cache)


def _cache_key(email: Mapping[str, Any], deps: ClassifierDeps) -> str:
    config = deps.config
    parts = (
        email.get("email_id"),
        email.get("from_address"),
        email.get("subject"),
        email.get("body"),
        config.prompt_version,
        config.summary_prompt_version,
    )
    return hashlib.sha256(json.dumps(parts, default=str).encode("utf-8")).hexdigest()


def _safe_line(text: str, max_chars: int) -> str:
    return mask_pii(clean_single_line(text, max_chars).text)[0]


def _subject_line(email: InboundEmail, deps: ClassifierDeps) -> str:
    return _safe_line(email.subject, deps.config.max_summary_chars) or "(no subject)"


def _quarantine_line(labels: Mapping[str, Any]) -> str:
    """Written by code, so an attacker's text cannot shape what HR reads about a quarantined email."""
    rules = labels.get("rules_applied") or []
    signals = next((rule.split(":", 1)[1] for rule in rules if rule.startswith("phishing:")), "")
    if signals:
        names = ", ".join(SIGNAL_NAMES.get(name, name.replace("_", " ")) for name in signals.split(","))
        return f"Quarantined as possible phishing. Warning signs: {names}."
    return "Quarantined as a possible prompt injection attempt."


def _summary_problems(summary: str, source_text: str, deps: ClassifierDeps) -> list[str]:
    problems = output_problems(summary, max_chars=deps.config.max_summary_chars)
    if not summary.strip():
        problems.append("empty")
    # An invented date, amount, or reference would look like a fact in HR's digest.
    source_numbers = set(re.findall(r"\d+", source_text))
    if any(number not in source_numbers for number in re.findall(r"\d+", summary)):
        problems.append("unsupported_number")
    if deps.detector is not None:
        try:
            if deps.detector(summary):
                problems.append("suspicious_text")
        except Exception as error:
            logger.warning("digest detector failed error_type=%s", type(error).__name__)
    return problems


def summarize_email(email: InboundEmail, labels: Mapping[str, Any], deps: ClassifierDeps) -> tuple[str, str]:
    """Return one line and where it came from. The model sees only this email, never a candidate's file."""
    if labels["type"] == EmailType.SUSPICIOUS.value:
        return _quarantine_line(labels), "quarantine_notice"
    # An email a person must answer gets a real summary even when its label is unhelpful.
    if (labels["type"] in _NO_MODEL_TYPES and not labels.get("needs_human")) or deps.llm is None:
        return _subject_line(email, deps), "subject"

    config = deps.config
    subject = clean_single_line(email.subject, config.max_subject_chars).text
    full_body = clean_untrusted_text(email.body, config.max_scan_chars).text
    body = model_view(full_body, config.max_email_chars)
    boundary = deps.boundary_factory()
    template = (_PROMPTS_DIR / f"{config.summary_prompt_version}.md").read_text(encoding="utf-8")
    user = "\n".join(
        [
            f"BEGIN_{boundary}",
            f"Subject: {remove_boundary(subject, boundary)}",
            remove_boundary(body, boundary),
            f"END_{boundary}",
            "",
            "Summarize this email as one JSON object.",
        ]
    )
    try:
        suggestion = generate_structured(
            deps.llm,
            LLMSummary,
            system=template.replace("{{BOUNDARY}}", boundary),
            user=user,
            timeout_s=config.llm_timeout_s,
        )
    except Exception as error:
        # Exception text can quote the prompt, so only its type is logged.
        logger.warning("digest summary failed error_type=%s", type(error).__name__)
        return _subject_line(email, deps), "subject_after_failure"

    summary = " ".join(suggestion.summary.split())
    problems = _summary_problems(summary, f"{subject}\n{body}", deps)
    if problems:
        logger.info("digest summary withheld email_id=%s problems=%s", email.email_id, ",".join(problems))
        return _subject_line(email, deps), "subject_after_check"
    prefix = PARTLY_READ_PREFIX if partly_read(full_body, config.max_email_chars) else ""
    return prefix + _safe_line(summary, config.max_summary_chars), "model"


def _classify_labels(email: InboundEmail, deps: ClassifierDeps) -> dict[str, Any]:
    result = classify_email(email, deps)
    labels = {field: getattr(result, field) for field in LABEL_FIELDS}
    labels["type"] = result.type.value
    labels["reason_code"] = result.reason_code
    return labels


def _sender_line(from_address: str, deps: ClassifierDeps) -> str:
    name, address = parseaddr(from_address.replace("\r", " ").replace("\n", " "))
    return clean_single_line(name or address or "(unknown sender)", deps.config.max_sender_chars).text


def collect_items(
    emails: list[dict[str, Any]],
    *,
    deps: ClassifierDeps,
    store: DigestStore,
    email_state: Callable[[str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Label and summarize each email. One bad email goes to a person and never stops the digest."""
    cache = store.load_cache()
    items = []
    for raw in emails:
        email_id = str(raw.get("email_id", "unknown"))
        state = email_state(email_id)
        key = _cache_key(raw, deps)
        cached = cache.get(key)
        try:
            email = InboundEmail.model_validate(raw)
        except ValidationError:
            invalid = code_only_result(email_id, EmailType.UNCLASSIFIED, "unknown", "invalid_email")
            items.append(
                {
                    "email_id": email_id,
                    "thread_id": str(raw.get("thread_id", "")),
                    "sender": "(invalid email)",
                    "subject": "(invalid email)",
                    "summary": "This email could not be read. Please check it manually.",
                    "summary_source": "invalid_email",
                    "received_at": str(raw.get("received_at", "")),
                    **{field: getattr(invalid, field) for field in LABEL_FIELDS if field != "type"},
                    "type": invalid.type.value,
                }
            )
            continue

        labels = state.get("classification")
        if labels:
            labels = {field: labels.get(field) for field in LABEL_FIELDS}
        elif cached:
            labels = cached["labels"]
        else:
            labels = _classify_labels(email, deps)
        if cached and cached["labels"].get("type") == labels.get("type"):
            summary, source = cached["summary"], cached["summary_source"]
        else:
            summary, source = summarize_email(email, labels, deps)

        if labels.get("reason_code") not in _RETRY_REASONS and source not in _RETRY_SOURCES:
            cache[key] = {"labels": labels, "summary": summary, "summary_source": source}
            store.save_cache(cache)
        items.append(
            {
                "email_id": email.email_id,
                "thread_id": email.thread_id,
                "sender": _sender_line(email.from_address, deps),
                "subject": _subject_line(email, deps),
                "summary": summary,
                "summary_source": source,
                "received_at": email.received_at.isoformat(),
                **{field: labels.get(field) for field in LABEL_FIELDS},
            }
        )
    return items


def _bucket(item: Mapping[str, Any], status: str) -> str:
    if item["type"] == EmailType.SUSPICIOUS.value or status == "quarantined":
        return "quarantined"
    if status == "awaiting_review":
        return "draft_waiting"
    if status in {"sent", "rejected", "stale", "send_failed"}:
        return "handled"
    if item.get("needs_human") or status == "needs_human":
        return "needs_answer"
    return "ready_to_draft" if item.get("can_draft") else "no_action"


def _order(item: Mapping[str, Any]) -> tuple[int, str]:
    return _URGENCY_RANK.get(str(item.get("urgency")), 1), str(item.get("received_at"))


def assemble_digest(record: Mapping[str, Any], email_state: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    """Group a stored digest by type and urgency, using each email's current status."""
    items = []
    for stored in record["items"]:
        state = email_state(stored["email_id"])
        labels = state.get("classification")
        merged = {**stored, **({field: labels.get(field) for field in LABEL_FIELDS} if labels else {})}
        status = state.get("status", "not_started")
        items.append({**merged, "workflow_status": status, "bucket": _bucket(merged, status)})
    items.sort(key=_order)

    groups = []
    for email_type, label in TYPE_LABELS.items():
        members = [item for item in items if item["type"] == email_type]
        if members:
            urgency = {level: sum(item["urgency"] == level for item in members) for level in _URGENCY_RANK}
            groups.append(
                {"type": email_type, "label": label, "total": len(members), "urgency": urgency, "items": members}
            )

    counts = {
        bucket: sum(item["bucket"] == bucket for item in items)
        for bucket in ("needs_answer", "draft_waiting", "quarantined", "ready_to_draft", "no_action", "handled")
    }
    return {
        "scope": record["scope"],
        "generated_at": record["generated_at"],
        "total": len(items),
        "counts": counts,
        "urgency": {level: sum(item["urgency"] == level for item in items) for level in _URGENCY_RANK},
        "headline": _headline(len(items), counts),
        "needs_answer": [item for item in items if item["bucket"] == "needs_answer"],
        "groups": groups,
    }


def _headline(total: int, counts: Mapping[str, int]) -> str:
    """Written by code from the counts, so it cannot be wrong or shaped by an email."""
    if not total:
        return "No emails in this period."
    return (
        f"{total} emails: {counts['needs_answer']} need a human answer, {counts['draft_waiting']} drafts are waiting "
        f"for approval, and {counts['quarantined']} are quarantined."
    )


def build_record(items: list[dict[str, Any]], scope: str) -> dict[str, Any]:
    return {"scope": scope, "generated_at": datetime.now(timezone.utc).isoformat(), "items": items}


def emails_in_scope(emails: list[dict[str, Any]], scope: str) -> list[dict[str, Any]]:
    """A date uses the day written in the email's own timestamp."""
    return (
        emails if scope == SCOPE_ALL else [email for email in emails if str(email.get("received_at", ""))[:10] == scope]
    )
