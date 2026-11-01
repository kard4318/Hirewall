# Evaluates the digest summaries and triage on a labeled dataset and reports metrics

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.paths import runtime_dir  # noqa: E402
from services.summarizer.digest_evaluation import (  # noqa: E402
    format_report,
    read_review_sheet,
    run_evaluation,
    score_results,
    score_review,
    write_review_sheet,
)
from services.summarizer.evaluation import read_json  # noqa: E402
from services.summarizer.node import load_default_deps  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate digest summaries on a labeled dataset.")
    parser.add_argument("--data", default="data/summarizer", help="folder with emails/inbox.json and expected.json")
    parser.add_argument("--split", default="tune", choices=["tune", "holdout", "all"])
    parser.add_argument("--runs", type=int, default=1, help="times to run each email, to measure stability")
    parser.add_argument("--from-run", help="score an earlier run's folder again, including its filled-in review sheet")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    data_dir = Path(args.data)
    if args.from_run:
        out_dir = Path(args.from_run)
        results = read_json(out_dir / "results.json")
    else:
        out_dir = runtime_dir() / "eval" / f"summarizer-{args.split}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        results = run_evaluation(data_dir, load_default_deps(), split=args.split, runs=args.runs, out_dir=out_dir)
        write_review_sheet(results, data_dir, out_dir / "review.csv")

    expected = read_json(data_dir / "expected.json")
    metrics = score_results(results, expected, read_json(data_dir / "emails" / "inbox.json"))
    if (out_dir / "review.csv").exists():
        metrics["human_review"] = score_review(read_review_sheet(out_dir / "review.csv"))
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(format_report(metrics))
    print(f"\nSaved in {out_dir}")
    return 0 if metrics["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
