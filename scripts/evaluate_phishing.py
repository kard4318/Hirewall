# Measures the phishing detector on labeled emails, plus the project's ordinary candidate and employee emails

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.paths import REPO_ROOT  # noqa: E402
from security.phishing_detector import assess_phishing  # noqa: E402

DATA = REPO_ROOT / "data"
ORDINARY_INBOXES = (
    "emails/inbox.json",
    "realistic/emails/inbox.json",
    "holdout/emails/inbox.json",
    "classifier/emails/inbox.json",
)
# These are scams, marketing, or attacks by design, so they do not count as ordinary email.
NOT_ORDINARY = {"c-23", "c-24", "c-25", "c-26", "c-27", "c-28", "c-29", "c-38", "c-42", "c-45", "r-337", "r-338"}


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def report(name: str, phishing: list[dict], legitimate: list[dict]) -> bool:
    def verdict(row: dict) -> str:
        return assess_phishing(f"{row['subject']}\n{row['body']}").verdict

    quarantined = [row for row in phishing if verdict(row) == "phishing"]
    flagged = [row for row in phishing if verdict(row) == "suspicious"]
    missed = [row for row in phishing if verdict(row) == "clean"]
    false_quarantine = [row for row in legitimate if verdict(row) == "phishing"]
    false_flag = [row for row in legitimate if verdict(row) == "suspicious"]
    print(f"\n{name}")
    if phishing:
        print(f"  Phishing quarantined:    {len(quarantined)}/{len(phishing)}")
        print(f"  Phishing sent to a person: {len(flagged)}/{len(phishing)}")
        print(f"  Phishing missed:         {len(missed)}/{len(phishing)}")
    if legitimate:
        print(f"  Normal email quarantined: {len(false_quarantine)}/{len(legitimate)}")
        print(f"  Normal email flagged for a person: {len(false_flag)}/{len(legitimate)}")
    for row in missed:
        print(f"    MISSED {row.get('id')}: {row['body'][:90]!r}")
    for row in false_quarantine + false_flag:
        result = assess_phishing(f"{row['subject']}\n{row['body']}")
        print(f"    FALSE ALARM {row.get('id', row.get('email_id'))} {result.signals}: {row['body'][:80]!r}")
    return not missed and not false_quarantine


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the phishing detector.")
    parser.add_argument("--split", default="tune", choices=["tune", "holdout"])
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    rows = load(DATA / "phishing" / "emails.json")
    chosen = [row for row in rows if row["split"] == args.split]
    phishing = [row for row in chosen if row["label"] == "phishing"]
    legitimate = [row for row in chosen if row["label"] == "legitimate"]
    passed = report(f"Labeled set ({args.split})", phishing, legitimate)
    if args.split == "tune":
        ordinary = [
            email for inbox in ORDINARY_INBOXES for email in load(DATA / inbox) if email["email_id"] not in NOT_ORDINARY
        ]
        passed = report("Ordinary project emails", [], ordinary) and passed
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
