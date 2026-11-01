# Evaluates the drafter on a labeled dataset and reports metrics

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.paths import runtime_dir  # noqa: E402
from orchestrator.approval import _DEFAULT_SIGNATURE  # noqa: E402
from services.drafter.evaluation import (  # noqa: E402
    format_report,
    read_review_sheet,
    run_evaluation,
    score_results,
    write_review_sheet,
)
from services.drafter.node import load_default_deps  # noqa: E402


def _load(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the drafter on a labeled dataset.")
    parser.add_argument("--data", default="data/realistic", help="folder with candidate_status.json and expected.json")
    parser.add_argument("--runs", type=int, default=2, help="times to run each email, to measure stability")
    parser.add_argument("--limit", type=int, help="only use the first N emails")
    parser.add_argument("--score", help="score an existing results.json folder instead of calling the model")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    data_dir = Path(args.data)
    if args.score:
        out_dir = Path(args.score)
        results = _load(out_dir / "results.json")
    else:
        out_dir = runtime_dir() / "eval" / datetime.now().strftime("%Y%m%d-%H%M%S")
        signature = os.getenv("RECRUITER_SIGNATURE") or _DEFAULT_SIGNATURE
        results = run_evaluation(
            data_dir, load_default_deps(), signature, runs=args.runs, out_dir=out_dir, limit=args.limit
        )
        count = write_review_sheet(results, data_dir, out_dir / "review.csv")
        print(f"\n{count} drafts are ready for review in {out_dir / 'review.csv'}")

    review_path = out_dir / "review.csv"
    review = read_review_sheet(review_path) if review_path.exists() else None
    metrics = score_results(
        results, _load(data_dir / "expected.json"), _load(data_dir / "candidate_status.json"), review
    )
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(format_report(metrics))
    print(f"\nSaved in {out_dir}")
    return 0 if metrics["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
