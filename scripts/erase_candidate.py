"""Erase one candidate from every local store (right to erasure). Stop the gateway first: it keeps scheduler state in
memory and would write it back. While it runs, use POST /api/hr/candidates/{id}/erase instead.

    python scripts/erase_candidate.py cand-1a2b3c4d5e6f            # asks you to type the ID again
    python scripts/erase_candidate.py cand-1a2b3c4d5e6f --yes --by admin.nour

Audit entries are kept: they hold IDs only, and the hash chain must stay verifiable.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from core.approval_queue.approval_queue import get_approval_queue  # noqa: E402
from core.audit.audit_log import get_audit_sink  # noqa: E402
from gateway.erasure import ErasureBlocked, erase_everywhere  # noqa: E402
from gateway.offline_stores import OfflineScheduler  # noqa: E402
from services.screener.service import ScreenerError, ScreeningService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_id")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--by", default="script", help="who asked for the erasure, for the audit log")
    args = parser.parse_args()
    if not args.yes and input(f"Type {args.candidate_id} to erase it everywhere: ").strip() != args.candidate_id:
        print("Not erased.")
        return 1
    try:
        counts = erase_everywhere(
            args.candidate_id, by=args.by, screening=ScreeningService(background=False, llm=None),
            queue=get_approval_queue(), audit=get_audit_sink(), scheduling=OfflineScheduler(),
        )
    except ErasureBlocked as error:
        print(f"Not erased: {error}. Cancel the interview on the Scheduling page first.")
        return 2
    except ScreenerError as error:
        print(f"Not erased: {error}")
        return 3
    print(f"Erased {args.candidate_id}: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
