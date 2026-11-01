# Tests for the JSON-backed mock calendar
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.scheduler.calendar_source.mock_calendar import MockCalendar

UTC = timezone.utc
START = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
END = datetime(2026, 11, 2, 10, 45, tzinfo=UTC)
DAY = (datetime(2026, 11, 2, tzinfo=UTC), datetime(2026, 11, 3, tzinfo=UTC))


@pytest.fixture
def calendar(tmp_path: Path) -> MockCalendar:
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps([{"start": "2026-11-02T09:00:00+00:00", "end": "2026-11-02T09:30:00+00:00"}]))
    return MockCalendar(path)


def test_loads_busy_blocks_from_json(calendar: MockCalendar) -> None:
    assert [b.start.hour for b in calendar.get_busy(*DAY)] == [9]


def test_create_is_idempotent_per_booking_id(calendar: MockCalendar) -> None:
    first, _ = calendar.create_event("bk-1", START, END, "Interview", ["candidate@example.com"])
    again, _ = calendar.create_event("bk-1", START, END, "Interview", ["candidate@example.com"])
    other, _ = calendar.create_event("bk-2", START, END, "Interview", [])
    assert first == again
    assert other != first
    assert len(calendar.get_busy(*DAY)) == 3  # seed block + two distinct events


def test_created_event_shows_as_busy(calendar: MockCalendar) -> None:
    calendar.create_event("bk-1", START, END, "Interview", [])
    assert any(b.start == START and b.end == END for b in calendar.get_busy(*DAY))


def test_cancel_frees_the_slot(calendar: MockCalendar) -> None:
    event_id, _ = calendar.create_event("bk-1", START, END, "Interview", [])
    calendar.cancel_event(event_id)
    assert all(b.start != START for b in calendar.get_busy(*DAY))
    calendar.cancel_event(event_id)  # second cancel is a no-op


def test_default_data_file_is_valid() -> None:
    busy = MockCalendar().get_busy(datetime(2026, 11, 4, tzinfo=UTC), datetime(2026, 11, 5, tzinfo=UTC))
    assert any(b.start.hour == 9 and b.end.hour == 17 for b in busy)  # fully booked 2026-11-04
