# LangGraph state for one candidate's scheduling conversation (JSON-friendly values only)
from typing import Any, TypedDict

from services.scheduler.models import TimeSlot


class SchedState(TypedDict, total=False):
    token: str
    candidate: dict[str, Any] | None
    user_message: str
    ui_action: dict[str, Any] | None
    blocked: bool
    block_reason: str | None
    understanding: dict[str, Any] | None
    offered: list[dict[str, str]]  # [{"id", "start", "end"}] ISO datetimes
    shown_starts: list[str]  # every slot start offered so far, so "other times" skips them
    pending_slot_id: str | None
    ready_to_book: bool
    booking: dict[str, Any] | None
    facts: dict[str, Any] | None  # what happened this turn; drives the reply
    reply: str | None
    turns: int  # messages received on this link
    recent_turns: list[str]  # ISO timestamps of messages in the last minute
    slot_searches: int  # slot searches run on this link


def slot_to_state(slot_id: str, slot: TimeSlot) -> dict[str, str]:
    return {"id": slot_id, "start": slot.start.isoformat(), "end": slot.end.isoformat()}


def state_to_slot(entry: dict[str, str]) -> TimeSlot:
    return TimeSlot(start=entry["start"], end=entry["end"])
