# Shared state object passed between workflow nodes

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkflowState(TypedDict, total=False):
    """Saved in checkpoints, so it holds IDs and outcomes. Email and draft text stay in the mailbox and queue."""

    task: str
    email_id: str
    status: str
    reason_code: str | None
    message: str | None
    approval_id: str | None
    decision: dict | None
    feedback: str | None
    result: dict | None
    classification: dict | None


class ReviewDecision(BaseModel):
    """What a human can do with a paused draft."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "edit", "redraft", "reject"]
    reviewer: str = Field(min_length=1, max_length=200)
    reviewed_hash: str | None = None
    subject: str | None = None
    body: str | None = None
    feedback: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _has_what_the_action_needs(self) -> "ReviewDecision":
        if not self.reviewer.strip():
            raise ValueError("reviewer_required")
        required = {
            "approve": [self.reviewed_hash],
            "edit": [self.subject, self.body],
            "redraft": [self.feedback],
            "reject": [],
        }[self.action]
        if any(not value for value in required):
            raise ValueError("missing_field")
        return self
