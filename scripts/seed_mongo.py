# Copies the project's fictional data (people, recruiting, handbook, runtime logs) into MongoDB Atlas collections
import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = "hirewall-seed"
FICTIONAL = re.compile(r"@([a-z0-9-]+\.)*example\.(test|com)$", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
DROP_FIELDS = {"event_link"}  # Google links encode the real calendar owner's address


def _scrub(value):  # noqa: ANN001, ANN202 - walks arbitrary JSON
    """Replace any non-fictional email address and drop fields that leak real identities."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in DROP_FIELDS}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, str):
        return EMAIL.sub(lambda m: m.group(0) if FICTIONAL.search(m.group(0)) else "redacted@example.test", value)
    return value


def _cell(text: str):  # noqa: ANN202
    if text == "":
        return None
    for kind in (int, float):
        try:
            return kind(text)
        except ValueError:
            pass
    return text


def read_csv(name: str, key: str | None = None) -> list[dict]:
    with (DATA / name).open(encoding="utf-8", newline="") as fh:
        rows = [{k: _cell(v) for k, v in row.items()} for row in csv.DictReader(fh)]
    return [{"_id": r[key], **r} if key else r for r in rows]


def read_json(name: str, key: str | None = None) -> list[dict]:
    raw = json.loads((DATA / name).read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else [raw]
    return [{"_id": r[key], **r} if key and key in r else r for r in rows]


def read_jsonl(name: str) -> list[dict]:
    return [json.loads(line) for line in (DATA / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def handbook() -> list[dict]:
    docs = []
    for path in sorted((DATA / "hr_documents").glob("*.md")):
        body = path.read_text(encoding="utf-8")
        title = next((line.lstrip("# ").strip() for line in body.splitlines() if line.startswith("#")), path.stem)
        docs.append({"_id": path.stem, "file": f"hr_documents/{path.name}", "title": title, "body": body})
    return docs


def scheduling() -> tuple[list[dict], list[dict]]:
    path = DATA / "runtime" / "scheduling_state.json"
    if not path.is_file():
        return [], []
    state = json.loads(path.read_text(encoding="utf-8"))
    statuses = [{"_id": cid, "candidate_id": cid, "status": s} for cid, s in state.get("status", {}).items()]
    bookings = [{"_id": b["booking_id"], **b} for b in state.get("bookings", [])]
    return statuses, bookings


def optional(name: str, reader, *args) -> list[dict]:  # noqa: ANN001
    return reader(name, *args) if (DATA / name).is_file() else []


def collections() -> dict[str, list[dict]]:
    statuses, bookings = scheduling()
    return {
        # People analytics: attributes and identities live in separate collections, joined only by employee_id
        "employees": read_csv("people/employees.csv", "employee_id"),
        "directory": read_csv("people/directory.csv", "employee_id"),
        "engagement": read_csv("people/engagement.csv"),
        "training_records": read_csv("people/training.csv"),
        "open_positions": read_csv("people/open_positions.csv"),
        # Recruiting
        "jobs": read_json("screener_mock/jobs.json", "job_id"),
        "candidates": read_json("screener_mock/candidates.json", "candidate_id"),
        "job_offers": read_json("job_offers/sample_job_offers.json"),
        "inbox_emails": read_json("emails/inbox.json", "email_id"),
        "calendar_busy": read_json("calendar/recruiter_calendar.json"),
        "candidate_status": statuses,
        "bookings": bookings,
        # Employee Q&A and governance
        "handbook_pages": handbook(),
        "knowledge_questions": optional("runtime/knowledge_log.json", read_json, "id"),
        "audit_events": optional("runtime/audit_events.jsonl", lambda n: read_jsonl(n)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy Hirewall's fictional data into MongoDB (replaces earlier seeds).")
    parser.add_argument("--dry-run", action="store_true", help="count documents only, no network")
    parser.add_argument("--clean", action="store_true", help="delete the seeded documents and stop")
    args = parser.parse_args()

    data = {name: [_scrub(doc) for doc in docs] for name, docs in collections().items()}
    if args.dry_run:
        for name, docs in data.items():
            print(f"  {name:20} {len(docs):5} documents")
        return 0

    env = dotenv_values(ROOT / ".env")
    if not env.get("MONGODB_URI"):
        print("MONGODB_URI is not set in .env")
        return 1
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    try:
        db = MongoClient(env["MONGODB_URI"], serverSelectionTimeoutMS=10000, appname="hirewall-seed")[
            env.get("MONGODB_DB") or "hirewall"]
        stamp = datetime.now(timezone.utc)
        for name, docs in data.items():
            coll = db[name]
            removed = coll.delete_many({"_seed": SEED}).deleted_count
            if args.clean:
                print(f"  {name:20} removed {removed}")
                continue
            if docs:
                coll.insert_many([{**doc, "_seed": SEED, "_seeded_at": stamp, "synthetic": True} for doc in docs],
                                 ordered=False)
            print(f"  {name:20} {coll.count_documents({'_seed': SEED}):5} documents")
        print(f"{'Cleaned' if args.clean else 'Seeded'} database '{db.name}'.")
    except PyMongoError as exc:
        print("FAILED:", type(exc).__name__, re.sub(r"//[^@\s]+@", "//***@", str(exc))[:400])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
