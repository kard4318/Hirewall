# Abstract interface for calendar data sources
from abc import ABC, abstractmethod
from datetime import datetime

from services.scheduler.models import TimeSlot


class CalendarProvider(ABC):
    @abstractmethod
    def get_busy(self, start: datetime, end: datetime) -> list[TimeSlot]:
        """Busy blocks overlapping [start, end)."""

    @abstractmethod
    def create_event(
        self, booking_id: str, start: datetime, end: datetime, summary: str, attendees: list[str]
    ) -> tuple[str, str | None]:
        """Create an event, idempotent per booking_id. Returns (event_id, link)."""

    @abstractmethod
    def cancel_event(self, event_id: str) -> None:
        """Cancel (delete) an event."""


class ReadOnlyCalendar:
    """The only calendar handle the scheduler service receives. Writes belong to core/executor."""

    def __init__(self, provider: CalendarProvider) -> None:
        self._provider = provider

    def get_busy(self, start: datetime, end: datetime) -> list[TimeSlot]:
        return self._provider.get_busy(start, end)

    def create_event(self, *args: object, **kwargs: object) -> tuple[str, str | None]:
        raise PermissionError("Scheduler has read-only calendar access; only core/executor may create events.")

    def cancel_event(self, *args: object, **kwargs: object) -> None:
        raise PermissionError("Scheduler has read-only calendar access; only core/executor may cancel events.")
