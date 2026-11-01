# Data models used by the drafter service

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:@<>+=\-]{1,256}$")]
ShortText = Annotated[str, StringConstraints(pattern=r"^[^\x00-\x1f\x7f]{1,200}$")]
DecisionType = Literal["advance", "reject", "offer", "hire", "salary"]
Intent = Literal["ack", "request_info", "status_update", "scheduling", "escalate"]


class ReasonCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    CANDIDATE_LOOKUP_UNAVAILABLE = "candidate_lookup_unavailable"
    UNKNOWN_SENDER = "unknown_sender"
    AMBIGUOUS_SENDER = "ambiguous_sender"
    INVALID_CANDIDATE_RECORD = "invalid_candidate_record"
    INJECTION_SUSPECTED = "injection_suspected"
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_FAILED = "llm_failed"
    LLM_ESCALATED = "llm_escalated"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    FORMAT_INVALID = "format_invalid"
    UNSUPPORTED_URL = "unsupported_url"
    UNSUPPORTED_EMAIL = "unsupported_email"
    UNDECIDED_OUTCOME = "undecided_outcome"
    INTERNAL_DATA = "internal_data"
    UNSUPPORTED_AMOUNT = "unsupported_amount"
    UNSUPPORTED_DATE = "unsupported_date"
    UNSUPPORTED_PHONE = "unsupported_phone"
    UNSUPPORTED_NUMBER = "unsupported_number"
    CLAIM_UNSUPPORTED = "claim_unsupported"
    CONTRADICTS_RECORD = "contradicts_record"
    REVISION_LIMIT_REACHED = "revision_limit_reached"
    INTERNAL_ERROR = "internal_error"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InboundEmail(_Strict):
    email_id: Identifier
    thread_id: Identifier
    from_address: str
    subject: str
    body: str
    received_at: datetime


class ThreadMessage(_Strict):
    thread_id: Identifier
    from_address: str
    direction: Literal["inbound", "outbound"]
    subject: str = ""
    body: str
    sent_at: datetime


class DraftRequest(_Strict):
    email: InboundEmail
    thread_history: list[ThreadMessage] = Field(default_factory=list)
    recruiter_signature: str = Field(min_length=1, max_length=500)
    approved_slots: list[datetime] = Field(default_factory=list)


class Interview(_Strict):
    scheduled_at: datetime
    location: ShortText | None = None


class HumanDecision(_Strict):
    type: DecisionType
    decided_by: ShortText
    decided_at: datetime
    details: ShortText | None = None


class DraftContext(_Strict):
    """Allowlisted facts the LLM may see. Only `thread` holds untrusted text."""

    candidate_id: Identifier
    first_name: ShortText
    job_title: ShortText
    stage: ShortText
    documents_received: list[ShortText] = Field(default_factory=list)
    documents_missing: list[ShortText] = Field(default_factory=list)
    interview: Interview | None = None
    proposed_slots: list[datetime] = Field(default_factory=list)
    decisions: list[HumanDecision] = Field(default_factory=list)
    recruiter_signature: str
    thread: list[ThreadMessage] = Field(default_factory=list)

    def trusted_view(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"thread"})


class Claim(_Strict):
    text: str
    source_field: str


class LLMDraft(_Strict):
    """The only shape accepted from the LLM. It has no recipient fields, by design."""

    intent: Intent
    language: str
    subject: str
    body: str
    claims: list[Claim]
    needs_human_input: str | None
    risk_flags: list[str]


class ProposedAction(_Strict):
    action_type: Literal["send_email"] = "send_email"
    candidate_id: str
    to: str
    subject: str
    body: str
    in_reply_to: str
    intent: Intent
    claims: list[Claim]
    warnings: list[str]
    payload_hash: str
    idempotency_key: str
    revision: int
    prompt_version: str


class DraftResult(_Strict):
    status: Literal["ready_for_review", "needs_human", "quarantined"]
    proposal: ProposedAction | None = None
    reason_code: ReasonCode | None = None
    human_message: str | None = None
