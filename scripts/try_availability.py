# Manual check: read busy blocks (read-only) and print proposed interview slots in local time
import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.scheduler import config  # noqa: E402
from services.scheduler.availability import find_free_slots  # noqa: E402
from services.scheduler.calendar_source.factory import get_calendar_provider  # noqa: E402
from services.scheduler.calendar_source.provider import ReadOnlyCalendar  # noqa: E402

WINDOW_DAYS = 10
FORMAT = "%a %Y-%m-%d %H:%M"


def main() -> int:
    parser = argparse.ArgumentParser(description="Print free interview slots for the next 10 days (read-only).")
    parser.add_argument("--provider", choices=["mock", "google"], help="overrides CALENDAR_PROVIDER")
    parser.add_argument("--max-slots", type=int, default=config.MAX_SLOTS)
    parser.add_argument("--per-day", type=int, default=config.PER_DAY)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    if args.provider:
        os.environ["CALENDAR_PROVIDER"] = args.provider

    try:
        tz = config.get_timezone()
        calendar = ReadOnlyCalendar(get_calendar_provider())
        now = datetime.now(tz)
        end = now + timedelta(days=WINDOW_DAYS)
        busy = calendar.get_busy(now, end)
    except Exception as exc:  # noqa: BLE001 - manual tool reports any failure clearly
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1

    working_days = sum((now.date() + timedelta(days=i)).weekday() < 5 for i in range(WINDOW_DAYS))
    slots = find_free_slots(busy, now, tz, days=working_days, max_slots=args.max_slots, per_day=args.per_day)

    print(f"Provider: {os.getenv('CALENDAR_PROVIDER', 'mock')}   Timezone: {tz}   Now: {now.strftime(FORMAT)}")
    print(f"\nBusy blocks ({len(busy)}):")
    for b in busy:
        print(f"  {b.start.astimezone(tz).strftime(FORMAT)} -> {b.end.astimezone(tz).strftime('%H:%M')}")
    print(f"\nProposed slots ({len(slots)}):")
    for s in slots:
        print(f"  {s.start.astimezone(tz).strftime(FORMAT)} -> {s.end.astimezone(tz).strftime('%H:%M')}")
    if not slots:
        print("  none free in the window")
    return 0


if __name__ == "__main__":
    sys.exit(main())
