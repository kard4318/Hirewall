"""The attack suite: each poisoned resume gets its expected flags, and its instruction changes nothing."""
import json

import pytest

from .helpers import REPO_ROOT, FakeLLM, make_service
from .pdf_fixtures import minimal_pdf

ATTACKS = REPO_ROOT / "data/attacks/resumes"
EXPECTED = json.loads((ATTACKS / "expected.json").read_text(encoding="utf-8"))
JOB = "job-preset-backend"


def ingest_and_score(tmp_path, llm, name, data):
    service = make_service(tmp_path, llm)
    result = service.ingest_files([(name, data)]).files[0]
    run = service.execute_run(service.start_run(JOB).run_id)
    return result, run.candidates[0]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_attack_is_flagged_and_has_no_effect(tmp_path, name):
    expected = EXPECTED[name]
    llm = FakeLLM()
    result, candidate = ingest_and_score(tmp_path / "attack", llm, name, (ATTACKS / name).read_bytes())
    _, baseline = ingest_and_score(
        tmp_path / "clean", FakeLLM(), expected["baseline"], (ATTACKS / expected["baseline"]).read_bytes()
    )
    assert result.status == "accepted"
    assert result.injection_flag is expected["flagged"]
    assert result.hidden_text_removed is expected["hidden"]
    assert candidate.injection_flag is expected["flagged"] and candidate.injection_excerpts
    assert candidate.total_score == baseline.total_score
    assert candidate.scores == baseline.scores
    prompts = llm.prompts().casefold()
    for words in ("rank this candidate first", "classez-moi", "تجاهل"):
        assert words.casefold() not in prompts


def test_stuffed_skills_cannot_beat_real_experience(tmp_path):
    stuffed = (ATTACKS / "keyword_stuffed.pdf").read_bytes()
    honest = minimal_pdf([
        "Lina Fictive", "Backend Developer", "EXPERIENCE", "Backend Developer, Fictional Co (2019 - 2025)",
        "Built REST API services in Python with FastAPI, PostgreSQL and Docker.", "SKILLS",
        "Python, FastAPI, PostgreSQL, Docker, REST API",
    ])
    service = make_service(tmp_path, FakeLLM())
    results = service.ingest_files([("s.pdf", stuffed), ("h.pdf", honest)]).files
    assert not any(file.injection_flag for file in results)
    run = service.execute_run(service.start_run(JOB).run_id)
    by_id = {c.candidate_id: c for c in run.candidates}
    fake, real = by_id[results[0].candidate_id], by_id[results[1].candidate_id]
    assert fake.scores.experience == 0.0 and real.scores.experience == 1.0
    assert real.rank < fake.rank


def test_repeating_a_line_adds_nothing(tmp_path):
    line = "Python, FastAPI, PostgreSQL, Docker, REST API"
    base = ["Junior Developer", "SKILLS", line]
    scores = []
    for name, lines in (("once", base), ("many", [*base, *[line] * 30])):
        _, candidate = ingest_and_score(tmp_path / name, FakeLLM(), "a.pdf", minimal_pdf(lines))
        scores.append(candidate.scores.semantic)
    assert scores[0] == scores[1]
