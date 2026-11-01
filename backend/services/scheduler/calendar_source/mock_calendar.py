# Mock calendar source backed by fictional JSON data
import json
import uuid
from datetime import datetime
from pathlib import Path

from services.scheduler.calendar_source.provider import CalendarProvider
from services.scheduler.config import REPO_ROOT
from services.scheduler.models import TimeSlot

DEFAULT_PATH = REPO_ROOT / "data" / "calendar" / "recruiter_calendar.json"


class MockCalendar(CalendarProvider):
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self._busy = [TimeSlot(start=b["start"], end=b["end"]) for b in raw]
        self._events: dict[str, TimeSlot] = {}  # event_id -> slot
        self._booking_events: dict[str, str] = {}  # booking_id -> event_id

    def get_busy(self, start: datetime, end: datetime) -> list[TimeSlot]:
        window = TimeSlot(start=start, end=end)
        blocks = self._busy + list(self._events.values())
        return sorted(
            (b for b in blocks if b.start < window.end and b.end > window.start),
            key=lambda b: b.start,
        )

    def create_event(
        self, booking_id: str, start: datetime, end: datetime, summary: str, attendees: list[str]
    ) -> tuple[str, str | None]:
        if booking_id in self._booking_events:
            return self._booking_events[booking_id], None
        event_id = f"mock-{uuid.uuid4().hex}"
        self._events[event_id] = TimeSlot(start=start, end=end)
        self._booking_events[booking_id] = event_id
        return event_id, None

    def cancel_event(self, event_id: str) -> None:
        # Idempotent: cancelling an unknown or already-cancelled event is a no-op.
        self._events.pop(event_id, None)
        self._booking_events = {b: e for b, e in self._booking_events.items() if e != event_id}
