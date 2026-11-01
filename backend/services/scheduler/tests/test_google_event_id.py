# Tests for the deterministic Google Calendar event id helper
import re

from services.scheduler.calendar_source.google_calendar import make_event_id


def test_is_deterministic() -> None:
    assert make_event_id("bk-123") == make_event_id("bk-123")


def test_is_40_hex_chars() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", make_event_id("bk-123"))


def test_different_booking_ids_differ() -> None:
    assert make_event_id("bk-1") != make_event_id("bk-2")
