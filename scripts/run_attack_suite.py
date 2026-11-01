"""Run the red-team attack suite and write data/runtime/attack_report.json and attack_report.md.

    python scripts/run_attack_suite.py              # offline: scripted models that obey the attacker
    python scripts/run_attack_suite.py --real       # screener attacks use the local Ollama model (LLM_MODEL)

Exits with status 1 if any attack gets through, so CI fails. Nothing here touches real data: each attack runs in its
own temporary folder, and the quarantine log is kept in memory.
"""
import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Before any import reads them: keep attack traffic out of the real logs and stores.
os.environ["SECURITY_QUARANTINE_FILE"] = ""
os.environ["HIREWALL_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="hirewall-attacks-")
os.environ.setdefault("SECURITY_MODEL_MODE", "off")

from security.attack_suite import injection_tests, poisoning_tests, upload_tests  # noqa: E402
from security.attack_suite.base import OWASP, run  # noqa: E402

REPORT_DIR = ROOT / "data" / "runtime"


def run_all(llm=None) -> list[dict]:
    results = []
    for module in (upload_tests, injection_tests, poisoning_tests):
        for attack in module.attacks(llm):
            results.append(run(attack))
            print(f"{results[-1]['result']:<5}{attack.id:<7}{attack.title}", flush=True)
    return results


def markdown(report: dict) -> str:
    lines = [
        "# Attack suite report", "",
        f"Run {report['generated_at']} ({report['mode']} models). "
        f"**{report['stopped']} of {report['total']} attacks stopped ({report['pass_rate']:.0%}).**", "",
        "| OWASP LLM 2025 | Attacks | Stopped |", "|---|---|---|",
    ]
    for code, name in OWASP.items():
        rows = [r for r in report["results"] if any(o.startswith(code) for o in r["owasp"])]
        if rows:
            lines.append(f"| {code} {name} | {len(rows)} | {sum(r['result'] == 'pass' for r in rows)} |")
    lines += ["", "| ID | Category | Attack | OWASP | Expected | Actual | Result |", "|---|---|---|---|---|---|---|"]
    for r in report["results"]:
        owasp = ", ".join(o.split()[0] for o in r["owasp"])
        lines.append(f"| {r['id']} | {r['category']} | {r['title']} | {owasp} | {r['expected']} | {r['actual']} | {r['result']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="use the local Ollama model for screener attacks")
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    args = parser.parse_args()
    llm = None
    if args.real:
        from core.llm.client import get_llm_client

        llm = get_llm_client()
    results = run_all(llm)
    stopped = sum(r["result"] == "pass" for r in results)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "real" if args.real else "offline",
        "total": len(results), "stopped": stopped, "failed": len(results) - stopped,
        "pass_rate": stopped / len(results) if results else 0.0,
        "by_category": dict(Counter(r["category"] for r in results)),
        "results": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "attack_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / "attack_report.md").write_text(markdown(report), encoding="utf-8")
    print(f"\n{stopped}/{len(results)} attacks stopped. Report: {args.out / 'attack_report.md'}")
    return 0 if stopped == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
