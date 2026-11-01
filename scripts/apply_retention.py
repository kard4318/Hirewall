"""Erase candidates whose recruiting process ended more than RETENTION_DAYS ago. Dry run unless --apply.

    python scripts/apply_retention.py            # lists who would be erased, and why
    python scripts/apply_retention.py --apply    # erases them (stop the gateway first)

A process has ended when every job the candidate was attached to is closed, when every decision recorded for them is
a rejection, or, for a candidate never attached to a job nor decided on, when they were added. Shortlisted candidates
in an open process are kept.
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from core.approval_queue.approval_queue import get_approval_queue  # noqa: E402
from core.audit.audit_log import get_audit_sink  # noqa: E402
from gateway.erasure import ErasureBlocked, erase_everywhere  # noqa: E402
from gateway.offline_stores import OfflineScheduler  # noqa: E402
from services.screener.service import ScreeningService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="erase; without it nothing changes")
    parser.add_argument("--days", type=int, default=int(os.getenv("RETENTION_DAYS", "365")))
    args = parser.parse_args()
    screening = ScreeningService(background=False, llm=None)
    due = screening.retention_due(datetime.now(timezone.utc), args.days)
    print(f"{len(due)} candidate(s) past {args.days} days" + ("" if args.apply else " (dry run, nothing erased)"))
    audit, failures = get_audit_sink(), 0
    for row in due:
        print(f"  {row['candidate_id']}  {row['reason']:<16} since {row['since'][:10]}")
        if not args.apply:
            continue
        try:
            erase_everywhere(row["candidate_id"], by="retention", screening=screening, queue=get_approval_queue(),
                             audit=audit, scheduling=OfflineScheduler())
        except ErasureBlocked as error:
            failures += 1
            print(f"    kept: {error}")
    if args.apply:
        audit.record("privacy.retention_applied", days=args.days, erased=len(due) - failures, kept=failures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
