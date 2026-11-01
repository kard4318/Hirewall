"""Add a named staff account to the local users file (HIREWALL_USERS_FILE, default data/runtime/users.json).

    python scripts/create_user.py                 # asks for each value; the password is typed twice and never shown
    python scripts/create_user.py --demo          # three demo accounts with random passwords, printed once
    python scripts/create_user.py --list

Roles: hr_admin (also manages users and sees the security page), recruiter (reviews and approves), employee (Q&A only).
"""
import argparse
import getpass
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from gateway.auth.login import MIN_PASSWORD, UserError, UserStore  # noqa: E402
from gateway.auth.roles import ROLE_AUDIENCE  # noqa: E402

DEMO = [("admin.demo", "Demo HR Admin", "hr_admin"), ("recruiter.demo", "Demo Recruiter", "recruiter"),
        ("employee.demo", "Demo Employee", "employee")]


def ask_password() -> str:
    while True:
        first = getpass.getpass(f"Password (at least {MIN_PASSWORD} characters): ")
        if first == getpass.getpass("Same password again: "):
            return first
        print("The two passwords differ. Try again.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    store = UserStore()

    if args.list:
        for user in store.list():
            print(f"{user.username:<24}{user.role:<12}{user.display_name}")
        return 0

    if args.demo:
        print(f"Writing to {store.path}. Save these passwords now: they are not stored anywhere.\n")
        for username, name, role in DEMO:
            password = secrets.token_urlsafe(12)
            try:
                store.add(username, name, role, password)
            except UserError as error:
                print(f"{username}: skipped ({error})")
                continue
            print(f"{username:<18}{role:<12}{password}")
        return 0

    username = input("Username (lowercase, e.g. sam.recruiter): ").strip().lower()
    display_name = input("Display name: ").strip()
    role = input(f"Role ({', '.join(ROLE_AUDIENCE)}): ").strip()
    try:
        user = store.add(username, display_name, role, ask_password())
    except UserError as error:
        print(f"Not created: {error}")
        return 1
    print(f"Created {user.username} ({user.role}) in {store.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
