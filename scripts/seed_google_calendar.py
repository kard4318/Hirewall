# Seeds the HR Google Calendar with the fictional busy blocks from data/calendar (and cleans them up)
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "calendar" / "recruiter_calendar.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
]
SEED_TAG = {"hirewall_seed": "1"}  # private extended property marking events this script owns
TITLES = ["Team sync", "Hiring committee", "1:1 with manager", "Onboarding session", "HR policy review",
          "Interview debrief", "Payroll check-in", "Training workshop"]


def load_blocks(start_monday: date | None) -> list[tuple[datetime, datetime]]:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    blocks = [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in raw]
    if start_monday:
        first = min(s for s, _ in blocks).date()
        shift = start_monday - (first - timedelta(days=first.weekday()))
        blocks = [(s + shift, e + shift) for s, e in blocks]
    return blocks


def title_for(index: int, start: datetime, end: datetime) -> str:
    if end - start >= timedelta(hours=8):
        return "Recruiting fair (all day)"
    return TITLES[index % len(TITLES)]


def build_service():  # noqa: ANN201 - googleapiclient resource has no public type
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token = ROOT / os.getenv("GOOGLE_TOKEN_FILE", "secrets/token.json")
    if not token.is_file():
        raise FileNotFoundError("Missing secrets/token.json: run `python scripts/google_auth.py` first.")
    return build("calendar", "v3", credentials=Credentials.from_authorized_user_file(str(token), SCOPES),
                 cache_discovery=False)


def list_seeded(service, calendar_id: str) -> list[dict]:  # noqa: ANN001
    events, page = [], None
    while True:
        resp = service.events().list(calendarId=calendar_id, privateExtendedProperty="hirewall_seed=1",
                                     singleEvents=True, showDeleted=False, pageToken=page).execute()
        events += resp.get("items", [])
        page = resp.get("nextPageToken")
        if not page:
            return events


def seed(blocks: list[tuple[datetime, datetime]], calendar_id: str, tz: str, dry_run: bool) -> None:
    service = None if dry_run else build_service()
    existing = set()
    if service:
        for ev in list_seeded(service, calendar_id):
            existing.add((datetime.fromisoformat(ev["start"]["dateTime"]), datetime.fromisoformat(ev["end"]["dateTime"])))
    created = skipped = 0
    for i, (start, end) in enumerate(blocks):
        title = title_for(i, start, end)
        if (start, end) in existing:
            skipped += 1
            continue
        print(f"  {'would create' if dry_run else 'create'}: {start:%a %Y-%m-%d %H:%M}-{end:%H:%M}  {title}")
        if service:
            body = {"summary": title,
                    "start": {"dateTime": start.isoformat(), "timeZone": tz},
                    "end": {"dateTime": end.isoformat(), "timeZone": tz},
                    "extendedProperties": {"private": SEED_TAG}}
            service.events().insert(calendarId=calendar_id, body=body, sendUpdates="none").execute()
        created += 1
    print(f"Seed done: {created} {'to create' if dry_run else 'created'}, {skipped} already present.")


def clean(calendar_id: str) -> None:
    service = build_service()
    events = list_seeded(service, calendar_id)
    for ev in events:
        service.events().delete(calendarId=calendar_id, eventId=ev["id"], sendUpdates="none").execute()
    print(f"Clean done: deleted {len(events)} seeded events (other events untouched).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed or clean fictional busy blocks in the HR Google Calendar.")
    parser.add_argument("--clean", action="store_true", help="delete only the events this script created")
    parser.add_argument("--dry-run", action="store_true", help="print what would be created, no Google calls")
    parser.add_argument("--start-monday", type=date.fromisoformat,
                        help="shift the data so its first week starts on this Monday (YYYY-MM-DD)")
    args = parser.parse_args()
    if args.start_monday and args.start_monday.weekday() != 0:
        parser.error("--start-monday must be a Monday")

    load_dotenv(ROOT / ".env")
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    try:
        if args.clean:
            clean(calendar_id)
        else:
            seed(load_blocks(args.start_monday), calendar_id, os.getenv("SCHEDULER_TIMEZONE", "Africa/Tunis"),
                 args.dry_run)
    except Exception as exc:  # noqa: BLE001 - manual tool reports any failure clearly
        status = getattr(getattr(exc, "resp", None), "status", None)
        print(f"FAILED: {type(exc).__name__}{f' (HTTP {status})' if status else ''}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
