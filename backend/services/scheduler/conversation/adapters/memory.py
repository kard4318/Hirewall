# In-memory adapters for repos, email, audit and clock (tests and the terminal demo)
from datetime import datetime
from typing import Any

from services.scheduler.models import Booking


class MemoryCandidateRepo:
    def __init__(self, candidates: dict[str, dict[str, Any]]) -> None:
        self._candidates = candidates

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        candidate = self._candidates.get(candidate_id)
        return dict(candidate) if candidate else None


class MemoryBookingRepo:
    def __init__(self) -> None:
        self._bookings: dict[str, Booking] = {}

    def get_active(self, candidate_id: str, job_id: str) -> Booking | None:
        return next(
            (b for b in self._bookings.values()
             if b.candidate_id == candidate_id and b.job_id == job_id and b.status == "booked"),
            None,
        )

    def save(self, booking: Booking) -> None:
        self._bookings[booking.booking_id] = booking

    def by_booking_id(self, booking_id: str) -> Booking | None:
        return self._bookings.get(booking_id)


class MemoryEmailSender:
    """Collects emails in `outbox`; nothing is really sent."""

    def __init__(self) -> None:
        self.outbox: list[dict[str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.outbox.append({"to": to, "subject": subject, "body": body})


class MemoryAuditLog:
    def __init__(self, clock: Any = None) -> None:
        self.entries: list[dict[str, Any]] = []
        self._clock = clock  # optional: stamps each entry with "at"

    def record(self, event: str, **fields: Any) -> None:
        stamp = {"at": self._clock.now().isoformat()} if self._clock else {}
        self.entries.append({"event": event, **stamp, **fields})

    def events(self) -> list[str]:
        return [e["event"] for e in self.entries]


class FixedClock:
    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now


class SystemClock:
    def __init__(self, tz: Any) -> None:
        self._tz = tz

    def now(self) -> datetime:
        return datetime.now(self._tz)
