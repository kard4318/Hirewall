# Evaluates the email classifier on a labeled dataset and reports metrics

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.paths import runtime_dir  # noqa: E402
from services.summarizer.evaluation import format_report, read_json, run_evaluation, score_results  # noqa: E402
from services.summarizer.node import load_default_deps  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the classifier on a labeled dataset.")
    parser.add_argument("--data", default="data/classifier", help="folder with emails/inbox.json and expected.json")
    parser.add_argument("--split", default="tune", choices=["tune", "holdout", "all"])
    parser.add_argument("--runs", type=int, default=2, help="times to run each email, to measure stability")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    data_dir = Path(args.data)
    out_dir = runtime_dir() / "eval" / f"classifier-{args.split}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    results = run_evaluation(data_dir, load_default_deps(), split=args.split, runs=args.runs, out_dir=out_dir)
    labels = [item for item in read_json(data_dir / "expected.json")]
    metrics = score_results(results, labels)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(format_report(metrics))
    print(f"\nSaved in {out_dir}")
    return 0 if metrics["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
