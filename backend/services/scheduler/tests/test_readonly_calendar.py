# Tests that the scheduler's read-only calendar wrapper blocks writes
from datetime import datetime, timezone

import pytest

from services.scheduler.calendar_source.mock_calendar import MockCalendar
from services.scheduler.calendar_source.provider import ReadOnlyCalendar

UTC = timezone.utc
START = datetime(2026, 11, 4, tzinfo=UTC)
END = datetime(2026, 11, 5, tzinfo=UTC)


def test_reads_are_forwarded() -> None:
    inner = MockCalendar()
    assert ReadOnlyCalendar(inner).get_busy(START, END) == inner.get_busy(START, END)


def test_writes_raise_permission_error() -> None:
    inner = MockCalendar()
    calendar = ReadOnlyCalendar(inner)
    with pytest.raises(PermissionError):
        calendar.create_event("bk-1", START, END, "Interview", [])
    with pytest.raises(PermissionError):
        calendar.cancel_event("any-id")
    assert inner.get_busy(START, END) == MockCalendar().get_busy(START, END)  # nothing was written
