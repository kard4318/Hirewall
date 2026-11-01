# Dev-only playground (superseded by /hr and /candidate): candidate chat plus an HR dashboard (fictional data only)
import argparse
import os
import secrets
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # scripts/dev_playground/ -> repo root
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from services.scheduler import config  # noqa: E402
from services.scheduler.calendar_source.factory import get_calendar_provider  # noqa: E402
from services.scheduler.calendar_source.provider import ReadOnlyCalendar  # noqa: E402
from services.scheduler.conversation.adapters.calendar_executor import (  # noqa: E402
    CalendarBookingExecutor,
    DryRunBookingExecutor,
)
from services.scheduler.conversation.adapters.memory import (  # noqa: E402
    FixedClock,
    MemoryAuditLog,
    MemoryBookingRepo,
    MemoryCandidateRepo,
    MemoryEmailSender,
    SystemClock,
)
from services.scheduler.conversation.deps import Deps  # noqa: E402
from services.scheduler.conversation.formatting import format_slot  # noqa: E402
from services.scheduler.conversation.graph import (  # noqa: E402
    build_graph,
    pending_approval,
    resume_booking,
    run_turn,
    thread_config,
)
from services.scheduler.conversation.llm import get_llm  # noqa: E402
from services.scheduler.conversation.state import state_to_slot  # noqa: E402
from services.scheduler.conversation.tokens import create_token, token_id  # noqa: E402

PAGE = Path(__file__).resolve().parent / "playground" / "index.html"
CANDIDATES = {  # fictional only
    "cand-sara": {"first_name": "Sara", "last_name": "Test", "email": "sara@example.test",
                  "job_id": "job-da", "job_title": "Data Analyst", "status": "approved_for_interview"},
    "cand-emily": {"first_name": "Emily", "last_name": "Test", "email": "emily@example.test",
                   "job_id": "job-da", "job_title": "Data Analyst", "status": "approved_for_interview"},
    "cand-yassine": {"first_name": "Yassine", "last_name": "Test", "email": "yassine@example.test",
                     "job_id": "job-be", "job_title": "Backend Developer", "status": "approved_for_interview"},
    "cand-lina": {"first_name": "Lina", "last_name": "Test", "email": "lina@example.test",
                  "job_id": "job-da", "job_title": "Data Analyst", "status": "screening"},
}


class ChatIn(BaseModel):
    token: str = Field(max_length=600)
    message: str | None = Field(default=None, max_length=2000)  # the agent enforces its own, lower limit
    action: dict[str, Any] | None = None


class ApprovalIn(BaseModel):
    approved: bool


class LinkIn(BaseModel):
    candidate_id: str


class ResetIn(BaseModel):
    strict: bool = False


class Playground:
    """Holds one in-memory world (calendar, repos, outbox, audit); reset rebuilds it."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.lock = threading.Lock()  # one graph run at a time keeps the in-memory adapters simple
        self.reset(strict=config.get_strict_booking_mode())

    def reset(self, strict: bool) -> None:
        settings = config.ConversationSettings(strict_booking=strict)
        clock = FixedClock(self.args.now) if self.args.now else SystemClock(settings.tz)
        provider = get_calendar_provider()
        google = os.getenv("CALENDAR_PROVIDER", "mock") == "google"
        executor = DryRunBookingExecutor() if google and not self.args.allow_write else CalendarBookingExecutor(provider)
        self.mode = ("Google Calendar, read-only (bookings are simulated)" if google and not self.args.allow_write
                     else "Google Calendar, real writes" if google else "mock calendar (in memory)")
        self.deps = Deps(llm=get_llm(self.args.llm), calendar=ReadOnlyCalendar(provider), executor=executor,
                         candidates=MemoryCandidateRepo(CANDIDATES), bookings=MemoryBookingRepo(),
                         email=MemoryEmailSender(), audit=MemoryAuditLog(), clock=clock, config=settings)
        self.graph = build_graph(self.deps)
        self.links: dict[str, str] = {}  # thread id -> candidate id, for the dashboard only
        self.pending: dict[str, dict[str, Any]] = {}  # thread id -> approval request

    def describe(self, result: dict[str, Any], token: str) -> dict[str, Any]:
        tz = self.deps.config.tz
        values = self.graph.get_state(thread_config(token)).values
        approval = pending_approval(result)
        if approval:
            self.pending[token_id(token)] = {**approval, "token": token,
                                             "candidate": self.links.get(token_id(token))}
        return {
            "thread": token_id(token),
            "reply": result.get("reply") if not approval else None,
            "kind": (result.get("facts") or {}).get("kind"),
            "blocked": bool(result.get("blocked")),
            "block_reason": result.get("block_reason"),
            "awaiting_hr": bool(approval),
            "pending_slot_id": values.get("pending_slot_id"),
            "slots": [{"id": s["id"], "label": format_slot(state_to_slot(s), tz)} for s in values.get("offered") or []],
            "booked": bool(values.get("booking")),
        }


def create_app(pg: Playground) -> FastAPI:
    app = FastAPI(title="Hirewall scheduler playground", docs_url=None, redoc_url=None)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(PAGE)

    @app.get("/api/info")
    def info() -> dict[str, Any]:
        now = pg.deps.clock.now().astimezone(pg.deps.config.tz)
        return {"mode": pg.mode, "llm": pg.args.llm or os.getenv("LLM_PROVIDER", "fake"),
                "timezone": str(pg.deps.config.tz), "now": f"{now:%a %d %b %Y, %H:%M}",
                "strict": pg.deps.config.strict_booking,
                "candidates": [{"id": cid, "name": f"{c['first_name']} {c['last_name']}", "job": c["job_title"],
                                "status": c["status"]} for cid, c in CANDIDATES.items()]}

    @app.post("/api/links")
    def new_link(body: LinkIn) -> dict[str, str]:
        if body.candidate_id not in CANDIDATES:
            raise HTTPException(404, "unknown candidate")
        c = CANDIDATES[body.candidate_id]
        token = create_token(body.candidate_id, c["job_id"], pg.deps.config.token_ttl_hours, pg.deps.clock.now())
        pg.links[token_id(token)] = body.candidate_id
        return {"token": token}

    @app.post("/api/chat")
    def chat(body: ChatIn) -> dict[str, Any]:
        with pg.lock:
            result = run_turn(pg.graph, body.token, message=body.message, ui_action=body.action)
            return pg.describe(result, body.token)

    @app.get("/api/approvals")
    def approvals() -> list[dict[str, Any]]:
        tz = pg.deps.config.tz
        return [{"thread": t, "candidate": CANDIDATES.get(r["candidate"] or "", {}).get("first_name", "?"),
                 "slot": format_slot(state_to_slot({"start": r["start"], "end": r["end"]}), tz)}
                for t, r in pg.pending.items()]

    @app.post("/api/approvals/{thread}")
    def decide(thread: str, body: ApprovalIn) -> dict[str, Any]:
        with pg.lock:
            request = pg.pending.pop(thread, None)  # HR acts on the stored request; it never needs the link
            if not request:
                raise HTTPException(404, "no pending approval")
            result = resume_booking(pg.graph, request["token"], approved=body.approved)
            return pg.describe(result, request["token"])

    @app.get("/api/calendar")
    def calendar() -> list[dict[str, Any]]:
        tz = pg.deps.config.tz
        now = pg.deps.clock.now().astimezone(tz)
        start = datetime.combine(now.date(), datetime.min.time(), tzinfo=tz)
        busy = pg.deps.calendar.get_busy(start, start + timedelta(days=pg.deps.config.window_days))
        interviews = {b.slot.start: CANDIDATES[b.candidate_id]["first_name"]
                      for b in pg.deps.bookings._bookings.values() if b.status == "booked"}  # type: ignore[attr-defined]
        return [{"day": f"{b.start.astimezone(tz):%a %d %b}",
                 "time": f"{b.start.astimezone(tz):%H:%M}-{b.end.astimezone(tz):%H:%M}",
                 "interview": interviews.get(b.start)} for b in busy]

    @app.get("/api/audit")
    def audit() -> list[dict[str, Any]]:
        return list(reversed(pg.deps.audit.entries))  # type: ignore[attr-defined]

    @app.get("/api/outbox")
    def outbox() -> list[dict[str, str]]:
        return list(reversed(pg.deps.email.outbox))  # type: ignore[attr-defined]

    @app.post("/api/reset")
    def reset(body: ResetIn) -> dict[str, bool]:
        with pg.lock:
            pg.reset(strict=body.strict)
        return {"ok": True}

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Web playground for the scheduling agent (http://127.0.0.1:8765).")
    parser.add_argument("--provider", choices=["mock", "google"], help="calendar (default: CALENDAR_PROVIDER or mock)")
    parser.add_argument("--llm", choices=["fake", "anthropic", "openai"], help="LLM (default: LLM_PROVIDER or fake)")
    parser.add_argument("--now", type=datetime.fromisoformat, help="fixed clock, ISO with offset")
    parser.add_argument("--allow-write", action="store_true", help="allow real Google Calendar writes when booking")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.now and args.now.tzinfo is None:
        parser.error("--now needs a UTC offset, e.g. 2026-11-02T08:00:00+01:00")

    load_dotenv(ROOT / ".env")
    if args.provider:
        os.environ["CALENDAR_PROVIDER"] = args.provider
    os.environ.setdefault("HR_NOTIFICATION_EMAIL", "hr@example.test")
    if not os.getenv("SCHEDULER_TOKEN_SECRET"):
        os.environ["SCHEDULER_TOKEN_SECRET"] = secrets.token_urlsafe(32)

    pg = Playground(args)
    if (args.llm or os.getenv("LLM_PROVIDER", "fake")) != "fake":
        print("Warming up the LLM (loading a local model can take a minute)...", flush=True)
        try:
            pg.deps.llm.generate('Reply with the JSON object {"ok": true}.', "ping")
        except Exception as exc:  # noqa: BLE001 - warm-up is best effort
            print(f"  warm-up failed ({type(exc).__name__})")
    print(f"Hirewall scheduler playground: http://127.0.0.1:{args.port}  ({pg.mode})")
    uvicorn.run(create_app(pg), host="127.0.0.1", port=args.port, log_level="warning")  # local only, never 0.0.0.0
    return 0


if __name__ == "__main__":
    sys.exit(main())
