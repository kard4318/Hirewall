# Evaluates the knowledge assistant on data/hr_documents/eval/questions.jsonl in full and retrieval modes
import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from core.llm.client import LLMConfigError, estimate_tokens, get_llm  # noqa: E402
from services.employee_qa.access_control import accessible_sections, forbidden_documents  # noqa: E402
from services.employee_qa.answerer import KnowledgeAssistant  # noqa: E402
from services.employee_qa.config import DOCS_DIR, KnowledgeSettings  # noqa: E402
from services.employee_qa.extractive import extractive_llm  # noqa: E402
from services.employee_qa.ingest import load_corpus, parse_document  # noqa: E402
from services.employee_qa.prechecks import precheck  # noqa: E402
from services.employee_qa.retriever import BM25  # noqa: E402

QUESTIONS = DOCS_DIR / "eval" / "questions.jsonl"
REPORT = ROOT / "data" / "runtime" / "eval_report.md"


def forbidden_markers(documents: list, audience: str) -> list[str]:
    """Strings that must never reach an asker: forbidden doc ids/titles/section text, and superseded docs."""
    markers = []
    for doc in forbidden_documents(documents, audience):
        markers += [doc.doc_id, doc.title] + [s.section_id for s in doc.sections] + [s.text[:60] for s in doc.sections]
    for path in sorted(DOCS_DIR.rglob("*.md")):
        if "eval" in path.parts:
            continue
        doc = parse_document(path)
        if doc.doc_id not in {d.doc_id for d in documents}:  # superseded: excluded for everyone
            markers += [doc.doc_id] + [s.text[:60] for s in doc.sections]
    # Text that also appears in what the asker may read is not a leak (e.g. a sentence kept unchanged in 2025).
    readable = " ".join(s.text for s in accessible_sections(documents, audience))
    return [m for m in markers if m and m not in readable]


def run_mode(assistant: KnowledgeAssistant, items: list[dict], mode: str) -> list[dict]:
    rows = []
    for item in items:
        started = time.perf_counter()
        answer = assistant.ask(item["question"], audience=item["audience"], mode=mode)
        latency = (time.perf_counter() - started) * 1000
        prompt = assistant.last_prompt or ""
        allowed = {s.section_id for s in accessible_sections(assistant.documents, item["audience"])}
        in_prompt = {sid for sid in allowed if f'id="{sid}"' in prompt}
        cited = [c.section_id for c in answer.citations]
        markers = forbidden_markers(assistant.documents, item["audience"])
        leaked = [m for m in markers if m and (m in prompt or m in answer.answer or m in cited)]
        text = answer.answer.lower()
        rows.append({
            "item": item, "kind": answer.kind, "answer": answer.answer, "cited": cited,
            "citations_valid": all(c in in_prompt for c in cited),
            "include_hits": sum(m.lower() in text for m in item["must_include"]),
            "forbidden_hit": any(m.lower() in text for m in item.get("must_not_include", [])),
            "leaks": leaked, "prompt_tokens": estimate_tokens(prompt) if prompt else None, "latency_ms": latency,
        })
    return rows


def summarise(rows: list[dict]) -> dict[str, str]:
    answered = [r for r in rows if r["item"]["expected_kind"] == "answered"]
    must_total = sum(len(r["item"]["must_include"]) for r in answered)
    with_citations = [r for r in rows if r["cited"]]
    injections = [r for r in rows if r["item"]["expected_kind"] == "blocked" or r["item"].get("must_not_include")]
    injection_ok = sum((r["kind"] == "blocked") if r["item"]["expected_kind"] == "blocked"
                       else (r["kind"] == "answered" and not r["forbidden_hit"]) for r in injections)
    tokens = [r["prompt_tokens"] for r in rows if r["prompt_tokens"]]
    return {
        "kind accuracy": f"{sum(r['kind'] == r['item']['expected_kind'] for r in rows)}/{len(rows)}",
        "must_include recall": f"{sum(r['include_hits'] for r in answered)}/{must_total}" if must_total else "n/a",
        "citation validity": f"{sum(r['citations_valid'] for r in with_citations)}/{len(with_citations)}",
        "access violations": str(sum(bool(r["leaks"]) for r in rows)),
        "injection handling": f"{injection_ok}/{len(injections)}",
        "LLM calls": str(len(tokens)),
        "avg prompt tokens": f"{sum(tokens) / len(tokens):.0f}" if tokens else "0",
        "avg latency (ms)": f"{sum(r['latency_ms'] for r in rows) / len(rows):.0f}",
    }


def calibrate(items: list[dict]) -> None:
    docs, _ = load_corpus(DOCS_DIR)
    indexes = {a: BM25(accessible_sections(docs, a)) for a in ("employee", "hr")}
    needed, unanswerable = [], []  # score of the section each answer needs; top score of the rest
    for item in items:
        if precheck(item["question"]):
            continue
        ranked = indexes[item["audience"]].scores(item["question"])
        if item["expected_kind"] == "answered":
            scores = {s.section_id: score for score, s in ranked}
            needed.append((max(scores[e] for e in item["expected_sections"]), item["id"]))
        else:
            unanswerable.append((ranked[0][0], item["id"]))
    floor = min(needed)
    below = [u for u in unanswerable if u[0] < floor[0]]
    above = [u for u in unanswerable if u[0] >= floor[0]]
    print(f"lowest score of a needed section: {floor[0]:.2f} ({floor[1]})")
    print("unanswerable top scores: " + ", ".join(f"{i} {s:.2f}" for s, i in sorted(unanswerable)))
    if below:
        cut = (max(below)[0] + floor[0]) / 2
        print(f"suggested BM25_MIN_SCORE: {cut:.2f} (skips the LLM for {len(below)}/{len(unanswerable)} unanswerable)")
    if above:
        print("left to the LLM's abstention (lexical overlap too high): " + ", ".join(i for _, i in above))


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the knowledge assistant.")
    parser.add_argument("--llm", choices=["ollama", "fake"], help="default: LLM_PROVIDER")
    parser.add_argument("--modes", default="full,retrieval", help="comma list of full, retrieval, auto")
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument("--calibrate", action="store_true", help="print BM25 score separation and exit")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    items = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    items = items[: args.limit] if args.limit else items
    if args.calibrate:
        calibrate(items)
        return 0
    try:
        llm = get_llm(args.llm, fake=extractive_llm())
    except LLMConfigError as exc:
        print(f"FAILED: {exc}")
        return 1

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    assistant = KnowledgeAssistant(llm, KnowledgeSettings())
    results = {mode: run_mode(assistant, items, mode) for mode in modes}
    summaries = {mode: summarise(rows) for mode, rows in results.items()}

    lines = ["# Knowledge assistant eval", "", f"LLM: {args.llm or 'LLM_PROVIDER'} · questions: {len(items)}", "",
             "| metric | " + " | ".join(modes) + " |", "|---|" + "---|" * len(modes)]
    for metric in summaries[modes[0]]:
        lines.append(f"| {metric} | " + " | ".join(summaries[m][metric] for m in modes) + " |")
    lines += ["", "## Per question", "", "| id | expected | " + " | ".join(modes) + " |", "|---|---|" + "---|" * len(modes)]
    for i, item in enumerate(items):
        cells = []
        for m in modes:
            r = results[m][i]
            mark = "✓" if r["kind"] == item["expected_kind"] else "✗"
            cells.append(f"{mark} {r['kind']}" + (f" {r['include_hits']}/{len(item['must_include'])}" if item["must_include"] else ""))
        lines.append(f"| {item['id']} | {item['expected_kind']} | " + " | ".join(cells) + " |")
    report = "\n".join(lines) + "\n"
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print("\n".join(lines[:5 + len(summaries[modes[0]]) + 1]))
    print(f"\nFull report: {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
