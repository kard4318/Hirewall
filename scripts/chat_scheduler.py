# Terminal chat with the scheduling agent for one fictional candidate (emails are only printed)
import argparse
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

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
from services.scheduler.conversation.llm import LLMConfigError, get_llm  # noqa: E402
from services.scheduler.conversation.state import state_to_slot  # noqa: E402
from services.scheduler.conversation.tokens import create_token  # noqa: E402

CANDIDATE_ID, JOB_ID = "cand-demo", "job-data-analyst"
HELP = "Type a message as the candidate, or /yes, /no, /quit"
DEBUG_HELP = "Type a message, or: /slot <id> (simulates a button click), /yes, /no, /quit"


class PrintingEmailSender(MemoryEmailSender):
    def send(self, to: str, subject: str, body: str) -> None:
        super().send(to, subject, body)
        print(f"  [email queued, not sent] to {to}: {subject}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chat with the Hirewall scheduling agent as a fictional candidate.")
    parser.add_argument("--provider", choices=["mock", "google"], help="calendar (default: CALENDAR_PROVIDER or mock)")
    parser.add_argument("--llm", choices=["fake", "anthropic", "openai"], help="LLM (default: LLM_PROVIDER or fake)")
    parser.add_argument("--now", type=datetime.fromisoformat, help="fixed clock, ISO with offset, e.g. 2026-11-02T08:00:00+01:00")
    parser.add_argument("--allow-write", action="store_true", help="allow real Google Calendar writes when booking")
    parser.add_argument("--name", default="Sara Test", help="fictional candidate's full name (as stored by HR)")
    parser.add_argument("--email", default="sara@example.test", help="fictional candidate's email (as stored by HR)")
    parser.add_argument("--debug", action="store_true", help="show slot ids after each reply and the audit log at the end")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not sys.stdin.isatty():  # piped input on Windows is not UTF-8 by default (breaks Arabic/French)
        sys.stdin.reconfigure(encoding="utf-8")
    load_dotenv(ROOT / ".env")
    if args.provider:
        os.environ["CALENDAR_PROVIDER"] = args.provider
    provider_name = os.getenv("CALENDAR_PROVIDER", "mock")
    if not os.getenv("SCHEDULER_TOKEN_SECRET"):
        os.environ["SCHEDULER_TOKEN_SECRET"] = secrets.token_urlsafe(32)
        print("note: SCHEDULER_TOKEN_SECRET not set, using a random secret for this session")
    if not os.getenv("HR_NOTIFICATION_EMAIL"):
        os.environ["HR_NOTIFICATION_EMAIL"] = "hr@example.test"
        print("note: HR_NOTIFICATION_EMAIL not set, using hr@example.test")

    try:
        settings = config.ConversationSettings()
        if args.now and args.now.tzinfo is None:
            print("--now needs a UTC offset, e.g. 2026-11-02T08:00:00+01:00")
            return 2
        clock = FixedClock(args.now) if args.now else SystemClock(settings.tz)
        provider = get_calendar_provider()
        llm = get_llm(args.llm)
    except (LLMConfigError, RuntimeError, ValueError) as exc:
        print(f"FAILED: {exc}")
        return 1

    if provider_name == "google" and not args.allow_write:
        executor = DryRunBookingExecutor()
        mode = "read-only (bookings are only printed; add --allow-write to create real events)"
    else:
        executor = CalendarBookingExecutor(provider)  # stand-in for core/executor
        mode = "writes to the real HR calendar" if provider_name == "google" else "in-memory mock calendar"

    first_name, _, last_name = args.name.strip().partition(" ")
    candidate = {"first_name": first_name or "Sara", "last_name": last_name, "email": args.email,
                 "job_id": JOB_ID, "job_title": "Data Analyst", "status": "approved_for_interview"}
    deps = Deps(llm=llm, calendar=ReadOnlyCalendar(provider), executor=executor,
                candidates=MemoryCandidateRepo({CANDIDATE_ID: candidate}), bookings=MemoryBookingRepo(),
                email=PrintingEmailSender(), audit=MemoryAuditLog(), clock=clock, config=settings)
    graph = build_graph(deps)
    token = create_token(CANDIDATE_ID, JOB_ID, settings.token_ttl_hours, clock.now())

    print(f"Calendar: {provider_name}, {mode}")
    llm_name = args.llm or os.getenv("LLM_PROVIDER", "fake")
    print(f"LLM: {llm_name}   Timezone: {settings.tz}   "
          f"Now: {clock.now().astimezone(settings.tz):%a %Y-%m-%d %H:%M}")
    if llm_name != "fake":
        print("Warming up the LLM (loading a local model can take a minute)...", flush=True)
        try:
            llm.generate('Reply with the JSON object {"ok": true}.', "ping")
        except Exception as exc:  # noqa: BLE001 - warm-up is best effort
            print(f"  warm-up failed ({type(exc).__name__}); replies fall back to fixed templates if this persists")
    print(f"Candidate (from HR records, via the signed link): {args.name} <{args.email}>, Data Analyst")
    print(f"{DEBUG_HELP if args.debug else HELP}\n")

    while True:
        try:
            line = input("candidate> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line in ("/quit", "/exit"):
            break
        if line.startswith("/slot"):
            result = run_turn(graph, token, ui_action={"type": "choose", "slot_id": line[5:].strip()})
        elif line == "/yes":
            result = run_turn(graph, token, ui_action={"type": "confirm"})
        elif line == "/no":
            result = run_turn(graph, token, ui_action={"type": "decline"})
        elif line.startswith("/"):
            print(DEBUG_HELP if args.debug else HELP)
            continue
        else:
            result = run_turn(graph, token, message=line)

        request = pending_approval(result)
        if request:
            answer = input(f"  [HR approval needed for {request['start']} -> {request['end']}] approve? [y/N] ")
            result = resume_booking(graph, token, approved=answer.strip().lower() in ("y", "yes"))

        print(f"agent> {result.get('reply')}")
        if args.debug:  # internal slot ids are for developers; the candidate only sees the numbered list
            offered = graph.get_state(thread_config(token)).values.get("offered") or []
            pending = result.get("pending_slot_id")
            for entry in offered:
                marker = "  <- pending" if entry["id"] == pending else ""
                print(f"    [{entry['id']}] {format_slot(state_to_slot(entry), settings.tz)}{marker}")
        print()

    if args.debug:
        print("Audit log:")
        for entry in deps.audit.entries:  # type: ignore[attr-defined]
            print(f"  {entry}")
    print("Outbox (nothing was sent):")
    for mail in deps.email.outbox:  # type: ignore[attr-defined]
        print(f"  to {mail['to']}: {mail['subject']}\n    " + mail["body"].replace("\n", "\n    "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
