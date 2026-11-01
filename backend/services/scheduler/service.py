# Scheduling service used by the gateway: HR invitations and bookings, candidate conversations
import dataclasses
import os
import threading
from typing import Any
from urllib.parse import quote

from services.scheduler import config
from services.scheduler.calendar_source.factory import get_calendar_provider
from services.scheduler.calendar_source.provider import ReadOnlyCalendar
from services.scheduler.conversation.adapters.calendar_executor import CalendarBookingExecutor, DryRunBookingExecutor
from core.integrations.email_provider import EmailDeliveryError, email_sender_from_env
from core.paths import runtime_dir
from services.scheduler.conversation.adapters.memory import MemoryAuditLog, SystemClock
from services.scheduler.conversation.adapters.screener_handoff import ScreenerHandoff
from services.scheduler.conversation.adapters.screener_mock import MockScreenerResults, ScreenerCandidateRepo
from services.scheduler.conversation.deps import Deps
from services.scheduler.conversation.formatting import format_slot
from services.scheduler.conversation.graph import build_graph, pending_approval, resume_booking, run_turn, thread_config
from services.scheduler.conversation.llm import get_llm
from services.scheduler.conversation.state import state_to_slot
from services.scheduler.conversation.tokens import TokenError, create_token, token_id, verify_token
from services.scheduler.models import Booking, Job, PassedCandidate
from services.scheduler.scheduling_state import STATUSES, SchedulingStateStore

def company_name() -> str:
    """Optional, from COMPANY_NAME in .env. Read when used, because the gateway loads .env after importing this."""
    return os.getenv("COMPANY_NAME", "").strip()


def at_company(company: str) -> str:
    return f" at {company}" if company else ""


HISTORY_LIMIT = 30
AWAITING_HR = "Thanks! Your chosen time is with HR for approval. You'll see the confirmation here."
INVITE_SUBJECT = "Book your interview for {job_title}{at_company}"
INVITE_BODY = (
    "Hi {first_name},\n\n"
    "Thank you for applying for the {job_title} position{at_company}. We'd like to invite you to an interview.\n"
    "Please choose a time that suits you here:\n{link}\n\n"
    "The link is personal and expires in {hours} hours.\n\n"
    "The HR team"
)


class LinkError(Exception):
    """The candidate link is invalid, expired, or no longer active."""


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class SchedulingService:
    def __init__(self, deps: Deps, screener: MockScreenerResults, state: SchedulingStateStore,
                 calendar_mode: str = "mock", public_base_url: str = "") -> None:
        self.deps = deps
        self.screener = screener
        self.state = state
        self.calendar_mode = calendar_mode
        self.public_base_url = public_base_url.rstrip("/")
        self.graph = build_graph(deps)
        self.lock = threading.Lock()  # one graph run or state change at a time
        self.links: dict[str, str] = {}      # candidate_id -> latest link (memory only: links are credentials)
        self.threads: dict[str, str] = {}    # token_id -> candidate_id
        self.history: dict[str, list[dict[str, str]]] = {}  # token_id -> last messages
        self.pending: dict[str, str] = {}    # booking_id -> token awaiting HR approval

    # --- HR side ------------------------------------------------------------------------------------------
    def jobs(self) -> list[dict[str, Any]]:
        result = []
        for job in self.screener.list_jobs():
            counts = dict.fromkeys(STATUSES, 0)
            for c in self.screener.list_passed(job.job_id):
                counts[self.state.status(c.candidate_id)] += 1
            result.append({"job_id": job.job_id, "title": job.title, "location": job.location,
                           "total": sum(counts.values()), "counts": counts})
        return result

    def candidates(self, job_id: str) -> list[dict[str, Any]]:
        if job_id not in {j.job_id for j in self.screener.list_jobs()}:
            raise NotFound(job_id)
        rows = []
        for c in self.screener.list_passed(job_id):
            status = self.state.status(c.candidate_id)
            booking = self.state.get_active(c.candidate_id, job_id)
            pending = next((b for b, t in self.pending.items() if self.threads.get(token_id(t)) == c.candidate_id), None)
            rows.append({
                **c.model_dump(mode="json"),
                "status": status,
                "candidate_link": self.links.get(c.candidate_id) if status == "invited" else None,
                "booking": self._booking_view(booking),
                "pending_booking_id": pending,
            })
        return rows

    def invite(self, candidate_id: str) -> str:
        with self.lock:
            record = self.screener.find(candidate_id)
            if record is None:
                raise NotFound(candidate_id)
            if self.state.status(candidate_id) in ("booked", "pending_approval"):
                raise Conflict("candidate already has a booking in progress")
            return self._send_invitation(record)[0]

    def invite_shortlisted(self, job: Job, record: PassedCandidate) -> bool:
        """Take over a candidate a recruiter shortlisted and approved. Returns whether the email went out."""
        with self.lock:
            if self.state.status(record.candidate_id) in ("booked", "pending_approval"):
                raise Conflict("candidate already has a booking in progress")
            self.screener.add(job, record)
            return self._send_invitation(record)[1]

    def withdraw_invitation(self, candidate_id: str) -> None:
        """A rejected candidate's link stops working. A confirmed booking stays until HR cancels it."""
        with self.lock:
            if self.state.status(candidate_id) in ("booked", "pending_approval") or not hasattr(self.screener, "remove"):
                return
            self.screener.remove(candidate_id)
            self.state.set_status(candidate_id, "passed")
            self.links.pop(candidate_id, None)

    def _send_invitation(self, record: PassedCandidate) -> tuple[str, bool]:
        hours = self.deps.config.token_ttl_hours
        token = create_token(record.candidate_id, record.job_id, hours, self.deps.clock.now())
        link = f"/candidate?token={quote(token, safe='')}"
        self.state.set_status(record.candidate_id, "invited")
        self.links[record.candidate_id] = link
        self.threads[token_id(token)] = record.candidate_id
        delivered = True
        try:
            self.deps.email.send(
                record.email,
                INVITE_SUBJECT.format(job_title=record.job_title, at_company=at_company(company_name())),
                INVITE_BODY.format(first_name=record.first_name, job_title=record.job_title,
                                   at_company=at_company(company_name()),
                                   link=self.public_base_url + link, hours=hours),
            )
        except EmailDeliveryError:
            # HR can still copy the link from the dashboard.
            delivered = False
            self.deps.audit.record("email_failed", candidate_id=record.candidate_id, job_id=record.job_id)
        self.deps.audit.record("invitation_created", candidate_id=record.candidate_id, job_id=record.job_id)
        return link, delivered

    def cancel(self, booking_id: str) -> None:
        with self.lock:
            booking = self.state.by_booking_id(booking_id)
            if booking is None or booking.status != "booked":
                raise NotFound(booking_id)
            if booking.event_id:
                self.deps.executor.cancel(booking.event_id)  # stand-in for core/executor: deletes the event
            self.state.save(booking.model_copy(update={"status": "cancelled"}))  # candidate back to passed
            self.links.pop(booking.candidate_id, None)
            self.deps.audit.record("booking_cancelled", candidate_id=booking.candidate_id, booking_id=booking_id)

    def decide(self, booking_id: str, approved: bool) -> None:
        with self.lock:
            token = self.pending.pop(booking_id, None)
            if token is None:
                raise NotFound(booking_id)
            result = resume_booking(self.graph, token, approved=approved)
            candidate_id = self.threads.get(token_id(token))
            if candidate_id and self.state.status(candidate_id) == "pending_approval":
                self.state.set_status(candidate_id, "invited")  # declined (or the slot was taken meanwhile)
            self._remember(token, "agent", result.get("reply") or "")

    def set_strict(self, enabled: bool) -> None:
        self.deps.config = dataclasses.replace(self.deps.config, strict_booking=enabled)

    def audit(self, limit: int = 30) -> dict[str, Any]:
        entries = self.deps.audit.entries  # type: ignore[attr-defined]
        latest = []
        for e in reversed(entries[-limit:]):
            candidate_id = e.get("candidate_id") or self.threads.get(e.get("thread") or "")
            latest.append({"at": e.get("at"), "event": e["event"], "reason": e.get("reason"),
                           "candidate": self._short_name(candidate_id)})
        return {"entries": latest, "blocked_count": sum(e["event"] == "message_blocked" for e in entries)}

    # --- candidate side -----------------------------------------------------------------------------------
    def check_link(self, token: str) -> dict[str, Any]:
        try:
            payload = verify_token(token, self.deps.clock.now())
        except TokenError as exc:
            raise LinkError() from exc
        record = self.deps.candidates.get_candidate(payload.candidate_id)
        if not record or record["job_id"] != payload.job_id or record["status"] != "approved_for_interview":
            raise LinkError()
        self.threads.setdefault(token_id(token), payload.candidate_id)
        return {**record, "candidate_id": payload.candidate_id}

    def conversation(self, token: str) -> dict[str, Any]:
        candidate = self.check_link(token)
        return {"first_name": candidate["first_name"], "job_title": candidate["job_title"],
                "company_name": company_name(), **self._view(token, candidate)}

    def message(self, token: str, text: str | None, action: dict[str, Any] | None) -> dict[str, Any]:
        with self.lock:
            candidate = self.check_link(token)
            self._remember(token, "candidate", self._describe_input(token, text, action))
            result = run_turn(self.graph, token, message=text, ui_action=action)
            approval = pending_approval(result)
            if approval:
                self.pending[approval["booking_id"]] = token
                self.state.set_status(candidate["candidate_id"], "pending_approval")
                reply = AWAITING_HR
            else:
                reply = result.get("reply") or ""
            self._remember(token, "agent", reply)
            return {"reply": reply, **self._view(token, candidate)}

    # --- helpers ------------------------------------------------------------------------------------------
    def _view(self, token: str, candidate: dict[str, Any]) -> dict[str, Any]:
        tz = self.deps.config.tz
        values = self.graph.get_state(thread_config(token)).values
        booking = self.state.get_active(candidate["candidate_id"], candidate["job_id"])
        return {
            "offered": [] if booking else [{"id": s["id"], "label": format_slot(state_to_slot(s), tz)}
                                          for s in values.get("offered") or []],
            "pending_slot_id": None if booking else values.get("pending_slot_id"),
            "booking": self._booking_view(booking, include_id=False),
            "awaiting_hr": self.state.status(candidate["candidate_id"]) == "pending_approval",
            "history": list(self.history.get(token_id(token), [])),
        }

    def _booking_view(self, booking: Booking | None, include_id: bool = True) -> dict[str, Any] | None:
        """include_id=True is the HR view. The candidate view omits ids and the HR event link,
        whose `eid` encodes the HR calendar's address."""
        if booking is None:
            return None
        view = {"start": booking.slot.start.isoformat(), "end": booking.slot.end.isoformat(),
                "label": format_slot(booking.slot, self.deps.config.tz)}
        return {"booking_id": booking.booking_id, **view, "link": booking.event_link} if include_id else view

    def _remember(self, token: str, role: str, text: str) -> None:
        if not text:
            return
        log = self.history.setdefault(token_id(token), [])
        log.append({"role": role, "text": text, "at": self.deps.clock.now().isoformat()})
        del log[:-HISTORY_LIMIT]

    def _describe_input(self, token: str, text: str | None, action: dict[str, Any] | None) -> str:
        if not action:
            return (text or "").strip()[: self.deps.config.max_message_chars]
        if action.get("type") == "choose":
            values = self.graph.get_state(thread_config(token)).values
            slot = next((s for s in values.get("offered") or [] if s["id"] == action.get("slot_id")), None)
            return format_slot(state_to_slot(slot), self.deps.config.tz) if slot else "(a time that was not offered)"
        return {"confirm": "Yes, book it", "decline": "No, another time"}.get(action.get("type"), "")

    def _short_name(self, candidate_id: str | None) -> str | None:
        record = self.screener.find(candidate_id) if candidate_id else None
        return f"{record.first_name} {record.last_name[:1]}." if record else None


def service_from_env() -> SchedulingService:
    """Real wiring from environment variables (.env); tests build SchedulingService with fakes instead."""
    settings = config.ConversationSettings()
    clock = SystemClock(settings.tz)
    provider = get_calendar_provider()
    google = os.getenv("CALENDAR_PROVIDER", "mock") == "google"
    allow_write = os.getenv("CALENDAR_ALLOW_WRITE", "false").lower() in ("1", "true", "yes")
    executor = CalendarBookingExecutor(provider) if (not google or allow_write) else DryRunBookingExecutor()
    mode = "google" if google and allow_write else "google-readonly" if google else "mock"
    screener = ScreenerHandoff(runtime_dir() / "scheduler_handoff.json", MockScreenerResults())
    state = SchedulingStateStore(config.REPO_ROOT / "data" / "runtime" / "scheduling_state.json")
    deps = Deps(llm=get_llm(), calendar=ReadOnlyCalendar(provider), executor=executor,
                candidates=ScreenerCandidateRepo(screener, state), bookings=state, email=email_sender_from_env(),
                audit=MemoryAuditLog(clock), clock=clock, config=settings)
    return SchedulingService(deps, screener, state, calendar_mode=mode,
                             public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:5173"))
