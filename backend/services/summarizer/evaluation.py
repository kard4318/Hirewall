# Measures the classifier on a labeled dataset

import json
import time
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.db.repositories import JsonCandidateDirectory

from .classify import ClassifierDeps
from .node import classify_node

FAILURE_CODES = {"llm_failed", "llm_unavailable", "candidate_lookup_unavailable", "invalid_email"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def run_evaluation(
    data_dir: Path, deps: ClassifierDeps, *, split: str, runs: int, out_dir: Path
) -> list[dict[str, Any]]:
    """Classify each email in the split. Nothing is written except the results file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = {item["email_id"]: item for item in read_json(data_dir / "expected.json")}
    emails = [
        email
        for email in read_json(data_dir / "emails" / "inbox.json")
        if email["email_id"] in labels and (split == "all" or labels[email["email_id"]].get("split") == split)
    ]
    deps = replace(deps, candidates=JsonCandidateDirectory(data_dir / "candidate_status.json"))
    results: list[dict[str, Any]] = []
    for run in range(1, runs + 1):
        for email in emails:
            started = time.monotonic()
            output = classify_node({"email": email}, deps)["classification"]
            results.append({"run": run, **output, "latency_s": round(time.monotonic() - started, 2)})
            (out_dir / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"  run {run} {email['email_id']}: {output['type']} needs_human={output['needs_human']}", flush=True)
    return results


def score_results(results: list[dict[str, Any]], expected: list[dict[str, Any]]) -> dict[str, Any]:
    """Score results. The gate fails on a missed human review, a wrong path to the drafter, or a model failure."""
    labels = {item["email_id"]: item for item in expected}
    scored = [result for result in results if result["email_id"] in labels]
    missed_human: list[str] = []
    wrongly_drafted: list[str] = []
    over_flagged: list[str] = []
    missed_draft: list[str] = []
    wrong_type: list[dict[str, Any]] = []
    wrong_urgency: list[dict[str, Any]] = []
    by_type: dict[str, Counter] = defaultdict(Counter)
    type_correct = urgency_correct = 0

    for result in scored:
        label = labels[result["email_id"]]
        email_id = result["email_id"]
        main_type = label["expected_types"][0]
        by_type[main_type]["total"] += 1
        if result["type"] in label["expected_types"]:
            type_correct += 1
            by_type[main_type]["correct"] += 1
        else:
            wrong_type.append({"email_id": email_id, "got": result["type"], "expected": label["expected_types"]})
        if result["urgency"] in label["expected_urgency"]:
            urgency_correct += 1
        else:
            wrong_urgency.append(
                {"email_id": email_id, "got": result["urgency"], "expected": label["expected_urgency"]}
            )
        if label["needs_human"] and not result["needs_human"]:
            missed_human.append(email_id)
        if not label["needs_human"] and result["needs_human"]:
            over_flagged.append(email_id)
        if result["can_draft"] and not label["can_draft"]:
            wrongly_drafted.append(email_id)
        if label["can_draft"] and not result["can_draft"]:
            missed_draft.append(email_id)

    by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in scored:
        by_email[result["email_id"]].append(result)
    repeated = [runs for runs in by_email.values() if len(runs) > 1]
    stable = sum(len({(run["type"], run["urgency"], run["needs_human"]) for run in runs}) == 1 for runs in repeated)
    latencies = sorted(result["latency_s"] for result in scored if "latency_s" in result)
    failures = [result["email_id"] for result in scored if result.get("reason_code") in FAILURE_CODES]
    needs_review = [item for item in scored if labels[item["email_id"]]["needs_human"]]
    return {
        "results_scored": len(scored),
        "type_accuracy": _rate(type_correct, len(scored)),
        "urgency_accuracy": _rate(urgency_correct, len(scored)),
        "missed_human": missed_human,
        "missed_human_rate": _rate(len(missed_human), len(needs_review)),
        "wrongly_drafted": wrongly_drafted,
        "over_flagged": over_flagged,
        "missed_draft": missed_draft,
        "wrong_type": wrong_type,
        "wrong_urgency": wrong_urgency,
        "by_type": {name: dict(count) for name, count in sorted(by_type.items())},
        "failures": failures,
        "latency_p50_s": latencies[len(latencies) // 2] if latencies else None,
        "same_label_across_runs": _rate(stable, len(repeated)),
        "gate_passed": not missed_human and not wrongly_drafted and not failures,
    }


def format_report(metrics: dict[str, Any]) -> str:
    def percent(value: float | None) -> str:
        return "n/a" if value is None else f"{value * 100:.0f}%"

    lines = [
        f"Results scored: {metrics['results_scored']}",
        "",
        "SAFETY (target: zero)",
        f"  Missed a needed human review: {len(metrics['missed_human'])} {metrics['missed_human'] or ''}",
        f"  Sent to the drafter wrongly:  {len(metrics['wrongly_drafted'])} {metrics['wrongly_drafted'] or ''}",
        "",
        "ACCURACY",
        f"  Correct type:    {percent(metrics['type_accuracy'])}",
        f"  Correct urgency: {percent(metrics['urgency_accuracy'])}",
        f"  Flagged for a person unnecessarily: {len(metrics['over_flagged'])} {metrics['over_flagged'] or ''}",
        f"  Could have drafted but did not:     {len(metrics['missed_draft'])} {metrics['missed_draft'] or ''}",
        "",
        "RELIABILITY",
        f"  Failures: {len(metrics['failures'])}",
        f"  Typical time per email: {metrics['latency_p50_s']}s",
        f"  Same labels across runs: {percent(metrics['same_label_across_runs'])}",
        "",
        "BY EXPECTED TYPE (correct / total)",
    ]
    for name, count in metrics["by_type"].items():
        lines.append(f"  {name:<24} {count.get('correct', 0):>2} / {count['total']}")
    if metrics["wrong_type"]:
        lines += ["", "WRONG TYPES"] + [f"  {item}" for item in metrics["wrong_type"]]
    if metrics["wrong_urgency"]:
        lines += ["", "WRONG URGENCY"] + [f"  {item}" for item in metrics["wrong_urgency"]]
    lines += ["", f"GATE: {'PASSED' if metrics['gate_passed'] else 'NEEDS ATTENTION'}"]
    return "\n".join(lines)
