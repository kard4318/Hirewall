# Manual smoke test of Google Calendar access: free/busy, create, delete a test event
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
]
ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "secrets" / "token.json"


def main() -> int:
    if not TOKEN_FILE.is_file():
        print("Missing secrets/token.json: run `python scripts/google_auth.py` first.")
        return 1
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    service = build("calendar", "v3", credentials=Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES),
                    cache_discovery=False)
    step = "1/3 free/busy"
    event_id = None
    try:
        now = datetime.now(timezone.utc)
        body = {"timeMin": now.isoformat(), "timeMax": (now + timedelta(days=7)).isoformat(),
                "items": [{"id": calendar_id}]}
        calendars = service.freebusy().query(body=body).execute().get("calendars", {})
        busy = next(iter(calendars.values()), {}).get("busy", [])
        print(f"Busy blocks in the next 7 days: {len(busy)}")
        for block in busy:
            print(f"  {block['start']} -> {block['end']}")
        print("1/3 free/busy OK")

        step = "2/3 create"
        start = datetime.combine(now.date() + timedelta(days=1), time(10, 0), tzinfo=timezone.utc)
        event = {"summary": "Hirewall smoke test",
                 "start": {"dateTime": start.isoformat()},
                 "end": {"dateTime": (start + timedelta(minutes=30)).isoformat()}}
        created = service.events().insert(calendarId=calendar_id, body=event, sendUpdates="none").execute()
        event_id = created["id"]
        print(f"Event link: {created.get('htmlLink')}")
        print("2/3 create OK")

        step = "3/3 delete"
        service.events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates="none").execute()
        print("3/3 delete OK")
        return 0
    except HttpError as exc:
        print(f"FAILED at step {step}: HTTP {exc.resp.status} {exc.reason}")
    except Exception as exc:  # noqa: BLE001 - smoke test reports any failure clearly
        print(f"FAILED at step {step}: {type(exc).__name__}: {exc}")
    if event_id and step == "3/3 delete":
        print("The test event was created but not deleted: remove 'Hirewall smoke test' tomorrow 10:00 UTC manually.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
