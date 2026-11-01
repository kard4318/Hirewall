# Tests for the pure free-slot finder
from datetime import datetime, timedelta, timezone

from services.scheduler.availability import find_free_slots
from services.scheduler.models import TimeSlot

UTC = timezone.utc
MONDAY = datetime(2026, 11, 2, tzinfo=UTC)  # 2026-11-02 is a Monday


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def block(day: int, start: tuple[int, int], end: tuple[int, int]) -> TimeSlot:
    return TimeSlot(start=at(day, *start), end=at(day, *end))


def test_skips_busy_blocks() -> None:
    busy = [block(2, (9, 0), (10, 0))]
    slots = find_free_slots(busy, MONDAY, UTC)
    assert slots[0].start == at(2, 10, 30)  # 10:00 + 15 min buffer, next 30-min step
    for slot in slots:
        assert all(slot.end <= b.start or slot.start >= b.end for b in busy)


def test_skips_weekends() -> None:
    friday_evening = at(6, 17, 0)
    slots = find_free_slots([], friday_evening, UTC)
    assert all(s.start.weekday() < 5 for s in slots)
    assert slots[0].start == at(9, 9, 0)  # next Monday


def test_respects_buffer() -> None:
    busy = [block(2, (9, 0), (9, 20))]
    assert find_free_slots(busy, MONDAY, UTC, buffer_minutes=0)[0].start == at(2, 9, 30)
    assert find_free_slots(busy, MONDAY, UTC)[0].start == at(2, 10, 0)
    # buffer before a busy block: 09:00-09:45 + 15 min would touch 10:00, so it is still allowed
    later = [block(2, (10, 0), (17, 0))]
    assert find_free_slots(later, MONDAY, UTC)[0].start == at(2, 9, 0)
    later_tight = [block(2, (9, 50), (17, 0))]
    assert find_free_slots(later_tight, MONDAY, UTC)[0].start.day == 3


def test_fully_booked_day_returns_nothing_for_that_day() -> None:
    busy = [block(4, (9, 0), (17, 0))]
    slots = find_free_slots(busy, at(4, 0), UTC)
    assert all(s.start.date() != at(4, 0).date() for s in slots)
    assert slots[0].start == at(5, 9, 0)


def test_one_slot_per_day_spread_across_days() -> None:
    slots = find_free_slots([], MONDAY, UTC)
    days = [s.start.date() for s in slots]
    assert len(slots) == 3
    assert len(set(days)) == 3
    assert days == sorted(days)


def test_per_day_limit_and_no_overlap_within_day() -> None:
    slots = find_free_slots([], MONDAY, UTC, per_day=2, max_slots=6)
    by_day: dict = {}
    for s in slots:
        by_day.setdefault(s.start.date(), []).append(s)
    assert all(len(v) <= 2 for v in by_day.values())
    first, second = by_day[MONDAY.date()]
    assert second.start >= first.end + timedelta(minutes=15)


def test_max_slots_respected() -> None:
    assert len(find_free_slots([], MONDAY, UTC, max_slots=2)) == 2
    assert len(find_free_slots([], MONDAY, UTC, max_slots=1, per_day=3)) == 1


def test_past_times_excluded() -> None:
    now = at(2, 11, 10)
    slots = find_free_slots([], now, UTC)
    assert all(s.start >= now for s in slots)
    assert slots[0].start == at(2, 11, 30)


def test_nothing_free_returns_empty_list() -> None:
    busy = [block(d, (9, 0), (17, 0)) for d in (2, 3, 4, 5, 6)]
    assert find_free_slots(busy, MONDAY, UTC) == []


def test_results_are_timezone_aware_and_in_working_hours_of_tz() -> None:
    paris_winter = timezone(timedelta(hours=1))
    slots = find_free_slots([], MONDAY, paris_winter)
    for s in slots:
        assert s.start.tzinfo is not None and s.start.utcoffset() is not None
        local = s.start.astimezone(paris_winter)
        assert 9 <= local.hour < 17
    assert slots[0].start == datetime(2026, 11, 2, 8, 0, tzinfo=UTC)  # 09:00 in UTC+1


def test_naive_from_dt_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        find_free_slots([], datetime(2026, 11, 2), UTC)
