# Data models used by the summarizer service

from datetime import datetime
try:
    from enum import StrEnum
except ImportError:  # Python 3.10: same behaviour as 3.11's StrEnum
    from enum import Enum

    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return str(self.value)
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:@<>+=\-]{1,256}$")]
SenderKind = Literal["candidate", "employee", "unknown"]
Urgency = Literal["high", "normal", "low"]


class EmailType(StrEnum):
    NEW_APPLICATION = "new_application"
    CANDIDATE_QUESTION = "candidate_question"
    INTERVIEW_SCHEDULING = "interview_scheduling"
    DOCUMENT_SUBMISSION = "document_submission"
    DECISION_OR_FEEDBACK = "decision_or_feedback"
    COMPENSATION = "compensation"
    WITHDRAWAL = "withdrawal"
    EMPLOYEE_QUESTION = "employee_question"
    AUTOMATIC_REPLY = "automatic_reply"
    UNRELATED = "unrelated"
    # Only code assigns these two. The model cannot choose them.
    SUSPICIOUS = "suspicious"
    UNCLASSIFIED = "unclassified"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InboundEmail(_Strict):
    email_id: Identifier
    thread_id: Identifier
    from_address: str
    subject: str
    body: str
    received_at: datetime


class LLMClassification(_Strict):
    """The only shape accepted from the model. It is a suggestion that code checks and can overrule."""

    type: Literal[
        "new_application",
        "candidate_question",
        "interview_scheduling",
        "document_submission",
        "decision_or_feedback",
        "compensation",
        "withdrawal",
        "employee_question",
        "automatic_reply",
        "unrelated",
    ]
    urgency: Urgency
    needs_human: bool
    reason: str


class Classification(_Strict):
    email_id: str
    type: EmailType
    urgency: Urgency
    needs_human: bool
    can_draft: bool
    sender_kind: SenderKind
    reason_code: str | None = None
    # May contain model text shaped by the sender, so it must be displayed as plain text and is not saved in workflows.
    reason: str | None = None
    rules_applied: list[str] = []
    prompt_version: str | None = None
