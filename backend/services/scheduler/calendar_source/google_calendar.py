# Google Calendar implementation of CalendarProvider (free/busy and events)
import hashlib
import logging
from datetime import datetime
from typing import Any

from services.scheduler.calendar_source.provider import CalendarProvider
from services.scheduler.models import TimeSlot

SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
]

logger = logging.getLogger(__name__)


def make_event_id(booking_id: str) -> str:
    """Deterministic Google event id (hex is valid base32hex), so retries never double-book."""
    return hashlib.sha256(booking_id.encode("utf-8")).hexdigest()[:40]


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GoogleCalendarProvider(CalendarProvider):
    def __init__(self, credentials: Any, calendar_id: str = "primary", send_updates: str = "none") -> None:
        from googleapiclient.discovery import build

        self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        self._calendar_id = calendar_id
        self._send_updates = send_updates

    def get_busy(self, start: datetime, end: datetime) -> list[TimeSlot]:
        window = TimeSlot(start=start, end=end)
        body = {
            "timeMin": window.start.isoformat(),
            "timeMax": window.end.isoformat(),
            "items": [{"id": self._calendar_id}],
        }
        response = self._service.freebusy().query(body=body).execute()
        calendars = response.get("calendars", {})
        calendar = calendars.get(self._calendar_id) or next(iter(calendars.values()), {})
        if calendar.get("errors"):
            raise RuntimeError(f"Free/busy query failed: {calendar['errors']}")
        return [TimeSlot(start=_parse_time(b["start"]), end=_parse_time(b["end"])) for b in calendar.get("busy", [])]

    def create_event(
        self, booking_id: str, start: datetime, end: datetime, summary: str, attendees: list[str]
    ) -> tuple[str, str | None]:
        from googleapiclient.errors import HttpError

        slot = TimeSlot(start=start, end=end)
        event_id = make_event_id(booking_id)
        body = {
            "id": event_id,
            "summary": summary,
            "start": {"dateTime": slot.start.isoformat()},
            "end": {"dateTime": slot.end.isoformat()},
            "attendees": [{"email": email} for email in attendees],
        }
        events = self._service.events()
        try:
            event = events.insert(
                calendarId=self._calendar_id, body=body, sendUpdates=self._send_updates
            ).execute()
            logger.info("Created calendar event %s for booking %s", event_id, booking_id)
        except HttpError as exc:
            if exc.resp.status != 409:
                raise
            event = events.get(calendarId=self._calendar_id, eventId=event_id).execute()
            if event.get("status") == "cancelled":
                raise RuntimeError(f"Booking {booking_id} maps to a cancelled event; use a new booking_id.") from exc
            logger.info("Event %s already exists for booking %s; reusing it", event_id, booking_id)
        return event["id"], event.get("htmlLink")

    def cancel_event(self, event_id: str) -> None:
        from googleapiclient.errors import HttpError

        try:
            self._service.events().delete(
                calendarId=self._calendar_id, eventId=event_id, sendUpdates=self._send_updates
            ).execute()
        except HttpError as exc:
            if exc.resp.status not in (404, 410):  # already gone counts as cancelled
                raise
        logger.info("Cancelled calendar event %s", event_id)
