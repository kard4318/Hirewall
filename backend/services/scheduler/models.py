# Data models used by the scheduler service
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TimeSlot(BaseModel):
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _end_after_start(self) -> "TimeSlot":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class Booking(BaseModel):
    booking_id: str
    candidate_id: str
    job_id: str
    slot: TimeSlot
    event_id: str | None = None
    event_link: str | None = None
    status: Literal["pending", "booked", "cancelled"] = "pending"


class Job(BaseModel):
    job_id: str
    title: str
    location: str = ""


class PassedCandidate(BaseModel):
    """Screener -> Scheduler handoff record (see docs/api-contract.md). Job-related criteria only."""

    candidate_id: str
    first_name: str
    last_name: str
    email: str
    job_id: str
    job_title: str
    score: int = Field(ge=0, le=100)
    matched_skills: list[str] = Field(default_factory=list)
    justification: str
    screened_at: datetime
