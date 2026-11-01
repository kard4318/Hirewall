# Builds the configured calendar provider (mock or Google) from environment variables
import os

from services.scheduler.calendar_source.mock_calendar import MockCalendar
from services.scheduler.calendar_source.provider import CalendarProvider, ReadOnlyCalendar
from services.scheduler.config import get_send_updates, resolve_path


class CalendarConfigError(RuntimeError):
    pass


def get_calendar_provider() -> CalendarProvider:
    """Full read/write provider. Only core/executor should call this."""
    name = os.getenv("CALENDAR_PROVIDER", "mock").strip().lower()
    if name == "mock":
        return MockCalendar()
    if name == "google":
        return _google_provider()
    raise CalendarConfigError(f"Unknown CALENDAR_PROVIDER {name!r}; use 'mock' or 'google'.")


def get_readonly_calendar() -> ReadOnlyCalendar:
    """The handle the scheduler service uses: free/busy reads only."""
    return ReadOnlyCalendar(get_calendar_provider())


def _google_provider() -> CalendarProvider:
    token_file = resolve_path(os.getenv("GOOGLE_TOKEN_FILE", "secrets/token.json"))
    if not token_file.is_file():
        raise CalendarConfigError(
            f"Google token file not found at {token_file}. Run `python scripts/google_auth.py` first."
        )
    from google.oauth2.credentials import Credentials

    from services.scheduler.calendar_source.google_calendar import SCOPES, GoogleCalendarProvider

    credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    return GoogleCalendarProvider(
        credentials,
        calendar_id=os.getenv("GOOGLE_CALENDAR_ID", "primary"),
        send_updates=get_send_updates(),
    )
