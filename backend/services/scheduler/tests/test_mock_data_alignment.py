# Tests that the mock recruiter calendar lines up with Africa/Tunis working hours
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from services.scheduler.availability import find_free_slots
from services.scheduler.calendar_source.mock_calendar import MockCalendar
from services.scheduler.config import get_timezone

TUNIS = ZoneInfo("Africa/Tunis")


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TUNIS)


@pytest.fixture(scope="module")
def busy() -> list:
    return MockCalendar().get_busy(local(1, 0), local(15, 0))


def slots_on(busy: list, day: int, per_day: int = 10) -> list[datetime]:
    slots = find_free_slots(busy, local(day, 0), TUNIS, days=1, per_day=per_day, max_slots=per_day)
    return [s.start for s in slots if s.start.day == day]


def test_default_timezone_is_tunis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCHEDULER_TIMEZONE", raising=False)
    assert str(get_timezone()) == "Africa/Tunis"


def test_busy_blocks_are_inside_local_working_hours(busy: list) -> None:
    weekday_blocks = [b for b in busy if b.start.astimezone(TUNIS).weekday() < 5]
    assert all(9 <= b.start.astimezone(TUNIS).hour and b.end.astimezone(TUNIS).hour <= 17 for b in weekday_blocks)


def test_fully_booked_day_has_no_slots(busy: list) -> None:
    assert slots_on(busy, 4) == []


def test_back_to_back_meetings_are_skipped_with_buffer(busy: list) -> None:
    starts = slots_on(busy, 5)
    assert local(5, 9, 0) in starts  # 09:00-09:45 ends right at the 15-min buffer before 10:00
    assert not any(local(5, 9, 30) <= s < local(5, 12, 15) for s in starts)
    assert local(5, 12, 30) in starts


def test_early_meeting_pushes_first_slot(busy: list) -> None:
    assert slots_on(busy, 6, per_day=1) == [local(6, 10, 0)]


def test_late_meeting_blocks_end_of_day(busy: list) -> None:
    starts = slots_on(busy, 9)
    assert max(starts) + timedelta(minutes=45) <= local(9, 15, 45)


def test_weekend_event_is_ignored_and_weekend_skipped(busy: list) -> None:
    assert any(b.start.astimezone(TUNIS).weekday() == 5 for b in busy)  # 2026-11-07 is in the data
    slots = find_free_slots(busy, local(6, 17, 0), TUNIS)
    assert slots[0].start == local(9, 9, 0)  # Friday evening -> Monday morning
