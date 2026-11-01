# Tests for SlotConstraints and stable slot ids in the free-slot finder
from datetime import date, datetime, time, timezone

from services.scheduler.availability import SlotConstraints, find_free_slots, stable_slot_id
from services.scheduler.models import TimeSlot

UTC = timezone.utc
MONDAY = datetime(2026, 11, 2, tzinfo=UTC)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def test_no_constraints_matches_default_behaviour() -> None:
    assert find_free_slots([], MONDAY, UTC) == find_free_slots([], MONDAY, UTC, constraints=SlotConstraints())


def test_weekdays_and_earliest() -> None:
    c = SlotConstraints(weekdays=frozenset({3}), earliest=time(14, 0))  # Thursdays after 14:00
    slots = find_free_slots([], MONDAY, UTC, days=10, constraints=c)
    assert slots and all(s.start.weekday() == 3 and s.start.time() >= time(14, 0) for s in slots)
    assert [s.start for s in slots] == [at(5, 14, 0), at(12, 14, 0)]


def test_latest_bounds_slot_end() -> None:
    c = SlotConstraints(latest=time(10, 0))
    slots = find_free_slots([], MONDAY, UTC, constraints=c)
    assert all(s.end.time() <= time(10, 0) for s in slots)


def test_earliest_stays_on_step_grid() -> None:
    c = SlotConstraints(earliest=time(14, 10))
    assert find_free_slots([], MONDAY, UTC, constraints=c)[0].start == at(2, 14, 30)


def test_date_range_and_exclusions() -> None:
    c = SlotConstraints(dates_from=date(2026, 11, 3), dates_to=date(2026, 11, 6), exclude_dates=frozenset({date(2026, 11, 5)}))
    days = [s.start.date() for s in find_free_slots([], MONDAY, UTC, constraints=c)]
    assert days == [date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 6)]


def test_single_date_allows_several_slots_that_day() -> None:
    c = SlotConstraints(dates_from=date(2026, 11, 3), dates_to=date(2026, 11, 3))
    slots = find_free_slots([], MONDAY, UTC, constraints=c)
    assert len(slots) == 3 and {s.start.date() for s in slots} == {date(2026, 11, 3)}


def test_single_fully_booked_date_returns_nothing() -> None:
    busy = [TimeSlot(start=at(4, 9), end=at(4, 17))]
    c = SlotConstraints(dates_from=date(2026, 11, 4), dates_to=date(2026, 11, 4))
    assert find_free_slots(busy, MONDAY, UTC, constraints=c) == []


def test_stable_slot_id() -> None:
    assert stable_slot_id(at(3, 10)) == stable_slot_id(at(3, 10))
    assert stable_slot_id(at(3, 10)) != stable_slot_id(at(3, 11))
    sid = stable_slot_id(at(3, 10))
    assert sid.startswith("s_") and len(sid) == 10
