# One-time Google OAuth login that saves secrets/token.json for the calendar provider
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
]
ROOT = Path(__file__).resolve().parents[1]
CLIENT_SECRET_FILE = ROOT / "secrets" / "client_secret.json"
TOKEN_FILE = ROOT / "secrets" / "token.json"


def main() -> int:
    if not CLIENT_SECRET_FILE.is_file():
        print("Missing secrets/client_secret.json: download the OAuth client (Desktop app) from Google Cloud Console.")
        return 1
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
    credentials = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
    print("Saved secrets/token.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
