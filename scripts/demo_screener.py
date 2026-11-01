"""Run the screener end to end with no gateway: ingest resumes, score one job, print the ranking.

    python scripts/demo_screener.py --demo --job job-preset-backend
    python scripts/demo_screener.py --resumes data/attacks/resumes --job job-preset-backend --fake-llm
    python scripts/demo_screener.py --demo --job job-preset-backend --fake-llm   # offline, no Ollama, no model download

With --fake-llm the rubric is a fixed placeholder and embeddings are a bag of words, so the numbers only show the
pipeline working. Results are stored under --runtime-dir (default: .runtime/screener-demo).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")


class PlaceholderLLM:
    """Stands in for Ollama in offline demos. Every rubric answer is the same."""

    model = "placeholder"

    def complete_json(self, *, system: str, user: str, json_schema: dict, timeout_s: float) -> Any:
        if "skills_coverage" in json_schema["properties"]:
            text = "Placeholder: no model was used."
            return {"skills_text": text, "skills_coverage": 5, "experience_text": text, "related_experience": 5,
                    "field_text": text, "field_closeness": 5}
        from services.screener.extract import split_sections

        match = re.search(r"BEGIN_\S+\n(.*)\nEND_", user, re.S)
        sections = [section.model_dump() for section in split_sections(match.group(1))]
        return json.dumps({"sections": sections, "profile": {}})


def percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.0%}"


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="load the fictional set in data/resumes")
    source.add_argument("--resumes", type=Path, help="folder of PDF and DOCX resumes")
    parser.add_argument("--job", default="job-preset-backend")
    parser.add_argument("--fake-llm", action="store_true", help="no Ollama and no model download")
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / ".runtime" / "screener-demo")
    args = parser.parse_args()

    os.environ["HIREWALL_RUNTIME_DIR"] = str(args.runtime_dir)
    from core.llm.embeddings import HashingEmbedder
    from services.screener.config import SemanticConfig
    from services.screener.service import MAX_FILES, ScreenerError, ScreeningService

    options: dict[str, Any] = {}
    if args.fake_llm:
        options = {"llm": PlaceholderLLM(), "embedder": HashingEmbedder(),
                   "semantic_config": SemanticConfig(floor=0.0, ceiling=0.6)}
    service = ScreeningService(background=False, **options)

    if args.demo:
        task = service.load_demo()
    else:
        paths = sorted(p for p in args.resumes.iterdir() if p.suffix.lower() in {".pdf", ".docx"})[:MAX_FILES]
        task = service.ingest_files([(p.name, p.read_bytes()) for p in paths])
    counts: dict[str, int] = {}
    for file in task.files:
        counts[file.status] = counts.get(file.status, 0) + 1
    print(f"Ingested {task.total} files: {counts}")

    try:
        run = service.execute_run(service.start_run(args.job).run_id)
    except ScreenerError as error:
        sys.exit(f"Could not start: {error}")
    if run.status != "done":
        sys.exit(f"Scoring failed: {run.reason_code}")

    print(f"\n{service.get_job(args.job).title}  (as of {run.as_of}, embeddings: {run.semantic_model_id}, model: {run.llm_model})\n")
    print(f"{'#':<4}{'candidate':<20}{'total':>6}{'semantic':>10}{'rubric':>8}{'exper.':>8}  profile")
    for c in run.candidates:
        marks = ("  [flagged]" if c.injection_flag else "") + ("  [hidden text]" if c.hidden_text_removed else "")
        print(f"{c.rank:<4}{c.candidate_id:<20}{percent(c.total_score):>6}{percent(c.scores.semantic):>10}"
              f"{percent(c.scores.rubric):>8}{percent(c.scores.experience):>8}  {c.profile}{marks}")

    flagged = [c for c in run.candidates if c.injection_flag]
    if flagged:
        print("\nRemoved as possible prompt injection:")
        for c in flagged:
            for line in c.injection_excerpts:
                print(f"  {c.candidate_id}: {line[:100]}")
    print("\nNothing was decided or recorded. A recruiter proposes a shortlist, and a person approves it.")


if __name__ == "__main__":
    main()
