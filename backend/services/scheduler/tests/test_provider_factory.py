# Tests for selecting the calendar provider from environment variables
from pathlib import Path

import pytest

from services.scheduler.calendar_source.factory import (
    CalendarConfigError,
    get_calendar_provider,
    get_readonly_calendar,
)
from services.scheduler.calendar_source.mock_calendar import MockCalendar
from services.scheduler.calendar_source.provider import ReadOnlyCalendar


def test_default_is_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CALENDAR_PROVIDER", raising=False)
    assert isinstance(get_calendar_provider(), MockCalendar)
    assert isinstance(get_readonly_calendar(), ReadOnlyCalendar)


def test_google_without_token_file_raises_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CALENDAR_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "missing_token.json"))
    with pytest.raises(CalendarConfigError, match="scripts/google_auth.py"):
        get_calendar_provider()


def test_unknown_provider_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CALENDAR_PROVIDER", "outlook")
    with pytest.raises(CalendarConfigError):
        get_calendar_provider()
