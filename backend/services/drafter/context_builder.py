# Gathers context needed to draft a reply

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from security.sanitizer import clean_single_line, clean_untrusted_text, normalize_address

from .config import DrafterConfig
from .models import DraftContext, DraftRequest, HumanDecision, Interview, ReasonCode, ThreadMessage


class CandidateDirectory(Protocol):
    def find_by_email(self, email: str) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class Resolution:
    record: Mapping[str, Any] | None = None
    email: str | None = None
    reason: ReasonCode | None = None


@dataclass
class BuiltContext:
    context: DraftContext
    warnings: list[str] = field(default_factory=list)


def resolve_candidate(from_address: str, directory: CandidateDirectory | None) -> Resolution:
    """Find the candidate from the sender address only, never from the email text."""
    if directory is None:
        return Resolution(reason=ReasonCode.CANDIDATE_LOOKUP_UNAVAILABLE)
    email = normalize_address(from_address)
    if email is None:
        return Resolution(reason=ReasonCode.UNKNOWN_SENDER)
    try:
        records = list(directory.find_by_email(email))
    except Exception:
        return Resolution(reason=ReasonCode.CANDIDATE_LOOKUP_UNAVAILABLE)

    matches = [record for record in records if normalize_address(str(record.get("email", ""))) == email]
    if not matches:
        return Resolution(reason=ReasonCode.UNKNOWN_SENDER)
    if len(matches) > 1:
        return Resolution(reason=ReasonCode.AMBIGUOUS_SENDER)
    return Resolution(record=matches[0], email=email)


def _clean_message(message: ThreadMessage, config: DrafterConfig, warnings: list[str]) -> ThreadMessage:
    subject = clean_single_line(message.subject, config.max_subject_chars)
    body = clean_untrusted_text(message.body, config.max_email_chars)
    if subject.hidden_removed or body.hidden_removed:
        warnings.append("hidden_content_removed")
    if body.truncated:
        warnings.append("email_truncated")
    return message.model_copy(update={"subject": subject.text, "body": body.text})


def _build_thread(request: DraftRequest, email: str, config: DrafterConfig, warnings: list[str]) -> list[ThreadMessage]:
    current = request.email
    messages: list[ThreadMessage] = []
    for message in request.thread_history:
        is_candidate = normalize_address(message.from_address) == email
        if message.thread_id != current.thread_id or (message.direction == "inbound" and not is_candidate):
            warnings.append("thread_message_excluded")
            continue
        messages.append(message)
    messages = messages[-(config.max_thread_messages - 1) :] if config.max_thread_messages > 1 else []
    messages.append(
        ThreadMessage(
            thread_id=current.thread_id,
            from_address=email,
            direction="inbound",
            subject=current.subject,
            body=current.body,
            sent_at=current.received_at,
        )
    )
    return [_clean_message(message, config, warnings) for message in messages]


def build_context(request: DraftRequest, record: Mapping[str, Any], email: str, config: DrafterConfig) -> BuiltContext:
    """Copy allowlisted fields only. Scores, notes, and other record fields are never read."""
    warnings: list[str] = []
    interview = record.get("interview")
    context = DraftContext(
        candidate_id=record["candidate_id"],
        first_name=record["first_name"],
        job_title=record["job_title"],
        stage=record["stage"],
        documents_received=list(record.get("documents_received") or []),
        documents_missing=list(record.get("documents_missing") or []),
        interview=(
            Interview(scheduled_at=interview["scheduled_at"], location=interview.get("location")) if interview else None
        ),
        proposed_slots=request.approved_slots,
        decisions=[
            HumanDecision(
                type=decision["type"],
                decided_by=decision["decided_by"],
                decided_at=decision["decided_at"],
                details=decision.get("details"),
            )
            for decision in record.get("decisions") or []
        ],
        recruiter_signature=request.recruiter_signature,
        thread=_build_thread(request, email, config, warnings),
    )
    return BuiltContext(context, list(dict.fromkeys(warnings)))
