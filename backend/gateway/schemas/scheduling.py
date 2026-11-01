# Request/response schemas for interview scheduling and follow-ups
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HRLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class HRToken(BaseModel):
    token: str
    expires_in_hours: int
    username: str
    display_name: str
    role: str


class StrictSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class CandidateAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["choose", "confirm", "decline"]
    slot_id: str | None = Field(default=None, max_length=32)


class CandidateMessage(BaseModel):
    """Either free text or a button action, never both."""

    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, max_length=2000)  # the agent enforces its own, lower limit
    action: CandidateAction | None = None

    @model_validator(mode="after")
    def _one_of(self) -> "CandidateMessage":
        if (self.text is None) == (self.action is None):
            raise ValueError("send either text or action")
        return self

    def ui_action(self) -> dict[str, Any] | None:
        return self.action.model_dump(exclude_none=True) if self.action else None
