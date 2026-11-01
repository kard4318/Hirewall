# BookingExecutor adapters: a calendar-backed stand-in for core/executor, and a dry-run variant
from services.scheduler.calendar_source.provider import CalendarProvider
from services.scheduler.models import TimeSlot


class CalendarBookingExecutor:
    """Stand-in for core/executor (not built yet): the only code that writes to the HR calendar.

    Only adapters may hold the full CalendarProvider; the graph itself gets a ReadOnlyCalendar.
    """

    def __init__(self, provider: CalendarProvider) -> None:
        self._provider = provider

    def book(self, booking_id: str, slot: TimeSlot, summary: str, attendees: list[str]) -> tuple[str, str | None]:
        return self._provider.create_event(booking_id, slot.start, slot.end, summary, attendees)

    def cancel(self, event_id: str) -> None:
        self._provider.cancel_event(event_id)


class DryRunBookingExecutor:
    """Prints what would be booked and writes nothing (used for Google without --allow-write)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def book(self, booking_id: str, slot: TimeSlot, summary: str, attendees: list[str]) -> tuple[str, str | None]:
        self.calls.append(booking_id)
        print(f"[dry-run] would create calendar event {slot.start.isoformat()} -> {slot.end.isoformat()} ({summary})")
        return f"dry-run-{booking_id[:12]}", None

    def cancel(self, event_id: str) -> None:
        print(f"[dry-run] would cancel calendar event {event_id}")
