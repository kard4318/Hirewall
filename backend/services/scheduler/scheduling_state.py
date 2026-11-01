# Per-candidate scheduling status and bookings, kept in memory with a JSON snapshot (demo persistence)
import json
import os
from pathlib import Path
from typing import Any, Literal

from services.scheduler.models import Booking

Status = Literal["passed", "invited", "pending_approval", "booked"]
STATUSES: tuple[str, ...] = ("passed", "invited", "pending_approval", "booked")


class SchedulingStateStore:
    """Implements the BookingRepo port, so bookings saved by the graph update the candidate status too."""

    def __init__(self, snapshot: Path | None = None) -> None:
        self._snapshot = snapshot
        self._status: dict[str, str] = {}
        self._bookings: dict[str, Booking] = {}
        if snapshot and snapshot.is_file():
            data = json.loads(snapshot.read_text(encoding="utf-8"))
            # An approval request cannot survive a restart (the paused graph is in memory), so fall back to invited.
            self._status = {cid: ("invited" if s == "pending_approval" else s) for cid, s in data.get("status", {}).items()}
            self._bookings = {b["booking_id"]: Booking.model_validate(b) for b in data.get("bookings", [])}

    # --- status -------------------------------------------------------------------------------------------
    def status(self, candidate_id: str) -> str:
        return self._status.get(candidate_id, "passed")

    def set_status(self, candidate_id: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        self._status[candidate_id] = status
        self._persist()

    # --- BookingRepo port ---------------------------------------------------------------------------------
    def get_active(self, candidate_id: str, job_id: str) -> Booking | None:
        return next((b for b in self._bookings.values()
                     if b.candidate_id == candidate_id and b.job_id == job_id and b.status == "booked"), None)

    def save(self, booking: Booking) -> None:
        self._bookings[booking.booking_id] = booking
        if booking.status == "booked":
            self._status[booking.candidate_id] = "booked"
        elif booking.status == "cancelled":
            self._status[booking.candidate_id] = "passed"
        self._persist()

    def by_booking_id(self, booking_id: str) -> Booking | None:
        return self._bookings.get(booking_id)

    def active_bookings(self) -> list[Booking]:
        return [b for b in self._bookings.values() if b.status == "booked"]

    def forget(self, candidate_id: str) -> int:
        """Drop the status and bookings of one candidate. Callers check first that nothing is still booked."""
        bookings = [key for key, booking in self._bookings.items() if booking.candidate_id == candidate_id]
        for key in bookings:
            del self._bookings[key]
        removed = len(bookings) + (1 if self._status.pop(candidate_id, None) is not None else 0)
        if removed:
            self._persist()
        return removed

    # --- persistence --------------------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {"status": dict(self._status), "bookings": [b.model_dump(mode="json") for b in self._bookings.values()]}

    def _persist(self) -> None:
        if not self._snapshot:
            return
        self._snapshot.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._snapshot.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")
        os.replace(tmp, self._snapshot)  # atomic on the same volume
