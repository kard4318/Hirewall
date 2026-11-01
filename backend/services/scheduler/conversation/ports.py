# Interfaces (ports) the scheduling conversation depends on; adapters implement them
from datetime import datetime
from typing import Any, Protocol

from services.scheduler.models import Booking, Job, PassedCandidate, TimeSlot


class CandidateRepo(Protocol):
    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        """Returns first_name, last_name (optional), email, job_id, job_title, status; None if unknown."""
        ...


class BookingRepo(Protocol):
    def get_active(self, candidate_id: str, job_id: str) -> Booking | None: ...

    def save(self, booking: Booking) -> None: ...

    def by_booking_id(self, booking_id: str) -> Booking | None: ...


class BookingExecutor(Protocol):
    """Write side of the calendar. Stand-in for core/executor; idempotent per booking_id."""

    def book(self, booking_id: str, slot: TimeSlot, summary: str, attendees: list[str]) -> tuple[str, str | None]: ...

    def cancel(self, event_id: str) -> None: ...


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class AuditLog(Protocol):
    def record(self, event: str, **fields: Any) -> None: ...


class ScreenerResults(Protocol):
    """Read side of the screener's output: who passed screening for which job."""

    def list_jobs(self) -> list[Job]: ...

    def list_passed(self, job_id: str) -> list[PassedCandidate]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
