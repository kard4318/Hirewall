# Manual test: create or cancel a real Google Calendar event through the scheduler's GoogleCalendarProvider
import argparse
import os
import sys
import uuid
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from services.scheduler.calendar_source.factory import get_calendar_provider  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="create an event and keep it")
    create.add_argument("--start", help="ISO start with offset, e.g. 2026-11-03T14:00:00+00:00 (default: tomorrow 11:00 UTC)")
    create.add_argument("--minutes", type=int, default=45)
    create.add_argument("--summary", default="Hirewall test interview")
    create.add_argument("--booking-id", help="reuse the same id to check idempotency (default: random)")
    cancel = sub.add_parser("cancel", help="delete an event by id")
    cancel.add_argument("event_id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.environ["CALENDAR_PROVIDER"] = "google"
    try:
        calendar = get_calendar_provider()
        if args.command == "cancel":
            calendar.cancel_event(args.event_id)
            print(f"Cancelled event {args.event_id}")
            return 0
        if args.start:
            start = datetime.fromisoformat(args.start)
        else:
            tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
            start = datetime.combine(tomorrow, time(11, 0), tzinfo=timezone.utc)
        booking_id = args.booking_id or f"manual-{uuid.uuid4().hex[:8]}"
        event_id, link = calendar.create_event(
            booking_id, start, start + timedelta(minutes=args.minutes), args.summary, attendees=[]
        )
    except Exception as exc:  # noqa: BLE001 - manual tool reports any failure clearly
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1
    print(f"Booking id: {booking_id}")
    print(f"Event id:   {event_id}")
    print(f"Start:      {start.isoformat()}")
    print(f"Link:       {link}")
    print(f"Delete it with: python scripts/google_try_event.py cancel {event_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
