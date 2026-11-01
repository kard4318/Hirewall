# Book node: re-checks the slot, books through the executor port, and sends fixed-template emails
import hashlib
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from langgraph.types import interrupt

from services.scheduler.conversation import fallbacks
from services.scheduler.conversation.deps import Deps
from services.scheduler.conversation.formatting import format_slot
from services.scheduler.conversation.nodes.find_slots import compute_offers
from services.scheduler.conversation.state import SchedState, state_to_slot
from services.scheduler.conversation.tokens import token_id
from services.scheduler.models import Booking, TimeSlot


def booking_id_for(thread: str, slot: TimeSlot) -> str:
    return hashlib.sha256(f"{thread}|{slot.start.isoformat()}".encode("utf-8")).hexdigest()


def make_node(deps: Deps) -> Callable[[SchedState], dict[str, Any]]:
    cfg = deps.config
    buffer = timedelta(minutes=cfg.buffer_minutes)

    def still_free(slot: TimeSlot) -> bool:
        if slot.start <= deps.clock.now():
            return False
        busy = deps.calendar.get_busy(slot.start - buffer, slot.end + buffer)
        return not any(slot.start < b.end + buffer and b.start - buffer < slot.end for b in busy)

    def taken(state: SchedState, slot_id: str) -> dict[str, Any]:
        deps.audit.record("slot_taken", thread=token_id(state["token"]), slot_id=slot_id)
        offered, _ = compute_offers(deps, None)
        return {"offered": offered, "pending_slot_id": None, "ready_to_book": False,
                "shown_starts": [s["start"] for s in offered],
                "facts": {"kind": "slot_taken", "slots": offered}}

    def send_emails(candidate: dict[str, Any], slot: TimeSlot, link: str | None, thread: str) -> None:
        when, tz_name, link_text = format_slot(slot, cfg.tz), str(cfg.tz), link or "(sent separately)"
        initial = f" {candidate['last_name'][:1]}." if candidate.get("last_name") else ""
        messages = [(candidate["email"],
                     fallbacks.CANDIDATE_EMAIL_SUBJECT.format(job_title=candidate["job_title"]),
                     fallbacks.CANDIDATE_EMAIL_BODY.format(first_name=candidate["first_name"], job_title=candidate["job_title"],
                                                           slot=when, timezone=tz_name, link=link_text))]
        if cfg.hr_email:
            name = f"{candidate['first_name']}{initial}"
            messages.append((cfg.hr_email,
                             fallbacks.HR_EMAIL_SUBJECT.format(candidate_name=name, job_title=candidate["job_title"]),
                             fallbacks.HR_EMAIL_BODY.format(candidate_name=name, job_title=candidate["job_title"],
                                                            slot=when, timezone=tz_name, link=link_text)))
        else:
            deps.audit.record("hr_email_missing", thread=thread)
        for to, subject, body in messages:
            try:
                deps.email.send(to, subject, body)
                deps.audit.record("email_sent", thread=thread, recipient="candidate" if to == candidate["email"] else "hr")
            except Exception as exc:  # noqa: BLE001 - a mail failure must not undo a booking
                deps.audit.record("email_failed", thread=thread, error=type(exc).__name__)

    def book(state: SchedState) -> dict[str, Any]:
        thread = token_id(state["token"])
        # Contact details come from the candidate repository at booking time, never from graph state or chat text.
        record = deps.candidates.get_candidate(state["candidate"]["candidate_id"]) or {}
        if not record.get("email"):
            deps.audit.record("booking_failed", thread=thread, error="candidate_missing")
            return {"ready_to_book": False, "facts": {"kind": "error"}}
        candidate = {**state["candidate"], "email": record["email"], "last_name": record.get("last_name", "")}
        pending = state.get("pending_slot_id")
        entry = next((s for s in state.get("offered") or [] if s["id"] == pending), None)
        if entry is None:
            return {"ready_to_book": False, "facts": {"kind": "need_choice", "slots": state.get("offered") or []}}
        slot = state_to_slot(entry)
        booking_id = booking_id_for(thread, slot)

        existing = deps.bookings.by_booking_id(booking_id)
        if existing and existing.status == "booked":  # replayed confirm: no second event, no second email
            return {"ready_to_book": False, "pending_slot_id": None, "facts": {"kind": "booked", "slot": entry}}
        if not still_free(slot):
            return taken(state, entry["id"])

        if deps.config.strict_booking:  # read at call time: HR can toggle it
            decision = interrupt({"kind": "booking_approval", "booking_id": booking_id,
                                  "candidate_id": candidate["candidate_id"], "job_id": candidate["job_id"],
                                  "slot_id": entry["id"], "start": entry["start"], "end": entry["end"]})
            if not (isinstance(decision, dict) and decision.get("approved") is True):
                deps.audit.record("booking_rejected", thread=thread, booking_id=booking_id)
                return {"ready_to_book": False, "pending_slot_id": None, "facts": {"kind": "booking_rejected"}}
            if not still_free(slot):  # time passed while waiting for approval
                return taken(state, entry["id"])

        summary = f"Interview: {candidate['first_name']} - {candidate['job_title']}"
        try:
            event_id, link = deps.executor.book(booking_id, slot, summary, attendees=[candidate["email"]])
        except Exception as exc:  # noqa: BLE001 - report, never crash the conversation
            deps.audit.record("booking_failed", thread=thread, booking_id=booking_id, error=type(exc).__name__)
            return {"ready_to_book": False, "facts": {"kind": "error"}}

        booking = Booking(booking_id=booking_id, candidate_id=candidate["candidate_id"], job_id=candidate["job_id"],
                          slot=slot, event_id=event_id, event_link=link, status="booked")
        deps.bookings.save(booking)
        deps.audit.record("booking_created", thread=thread, booking_id=booking_id, slot_id=entry["id"], event_id=event_id)
        send_emails(candidate, slot, link, thread)
        return {"ready_to_book": False, "pending_slot_id": None,
                "booking": booking.model_dump(mode="json"),
                "facts": {"kind": "booked", "slot": entry, "link": link}}

    return book
