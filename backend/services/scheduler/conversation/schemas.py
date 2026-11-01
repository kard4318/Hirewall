# Strict Pydantic schemas for everything the LLM returns in the scheduling conversation
from datetime import date, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from services.scheduler.availability import SlotConstraints
from services.scheduler.conversation.formatting import reply_problems

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
Intent = Literal["ask_slots", "choose_slot", "confirm", "decline", "question", "other"]


class Preference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dates_from: date | None = None
    dates_to: date | None = None
    weekdays: list[Weekday] | None = Field(default=None, max_length=7)
    earliest: time | None = None
    latest: time | None = None
    exclude_dates: list[date] = Field(default_factory=list, max_length=31)

    @model_validator(mode="after")
    def _ranges(self) -> "Preference":
        if self.dates_from and self.dates_to and self.dates_from > self.dates_to:
            raise ValueError("dates_from must not be after dates_to")
        if self.earliest and self.latest and self.earliest >= self.latest:
            raise ValueError("earliest must be before latest")
        return self

    def to_constraints(self) -> SlotConstraints:
        return SlotConstraints(
            dates_from=self.dates_from,
            dates_to=self.dates_to,
            weekdays=frozenset(WEEKDAY_INDEX[d] for d in self.weekdays) if self.weekdays else None,
            earliest=self.earliest,
            latest=self.latest,
            exclude_dates=frozenset(self.exclude_dates),
        )


class Understanding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    preference: Preference | None = None
    slot_ref: str | None = Field(default=None, max_length=40)
    more_options: bool = False  # candidate wants times other than the ones already shown


class ReplyText(BaseModel):
    """LLM-worded reply; validation context carries the required placeholder."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=600)

    @field_validator("message")
    @classmethod
    def _safe(cls, value: str, info: ValidationInfo) -> str:
        context = info.context or {}
        problem = reply_problems(value, context.get("placeholder"), booked=context.get("booked", False))
        if problem:
            raise ValueError(problem)
        return value


class AnswerText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=400)

    @field_validator("answer")
    @classmethod
    def _safe(cls, value: str) -> str:
        problem = reply_problems(value, None, max_chars=400)
        if problem:
            raise ValueError(problem)
        return value
