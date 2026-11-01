# Tests that the synthetic people-data generator is deterministic and only writes fictional, pseudonymous data
import csv
import importlib.util
import json
from datetime import date
from pathlib import Path

GENERATOR = Path(__file__).resolve().parents[4] / "scripts" / "generate_people_data.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_people_data", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(tmp: Path, seed: int = 42) -> Path:
    load_generator().generate(seed, date(2026, 11, 1), tmp / "people", tmp / "audit.jsonl")
    return tmp


def test_same_seed_gives_identical_files(tmp_path: Path) -> None:
    a, b = run(tmp_path / "a"), run(tmp_path / "b")
    for name in ("people/employees.csv", "people/engagement.csv", "people/training.csv", "people/open_positions.csv",
                 "people/directory.csv", "audit.jsonl"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    c = run(tmp_path / "c", seed=7)
    assert (c / "people/employees.csv").read_bytes() != (a / "people/employees.csv").read_bytes()


def test_people_are_pseudonymous_and_limited_to_allowed_fields(tmp_path: Path) -> None:
    root = run(tmp_path)
    rows = list(csv.DictReader((root / "people/employees.csv").open(encoding="utf-8")))
    assert set(rows[0]) == {"employee_id", "department", "job_title", "level", "site", "contract", "hire_date", "end_date",
                            "exit_type", "exit_reason", "age_band", "gender", "manager_id"}
    assert all(r["employee_id"].startswith("E-") for r in rows)
    active = [r for r in rows if not r["end_date"]]
    assert 380 <= len(active) <= 420 and 100 <= len(rows) - len(active) <= 140


def test_audit_events_are_synthetic_and_contract_shaped(tmp_path: Path) -> None:
    events = [json.loads(line) for line in (run(tmp_path) / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    allowed = {"ts", "event", "actor", "reason_code", "job_id", "candidate_ref", "outcome", "topic", "synthetic"}
    assert events and all(e["synthetic"] is True and set(e) <= allowed for e in events)
    assert {e["event"] for e in events} == {"resume_screened", "candidate_shortlisted", "invitation_created",
                                            "booking_created", "booking_cancelled", "reminder_drafted",
                                            "approval_decided", "kb_question", "message_blocked"}
    assert all(e["ts"] < "2026-11-02" for e in events)


def test_directory_names_are_fictional_and_kept_apart(tmp_path: Path) -> None:
    root = run(tmp_path)
    rows = list(csv.DictReader((root / "people/directory.csv").open(encoding="utf-8")))
    assert set(rows[0]) == {"employee_id", "first_name", "last_name", "email"}
    assert all(r["email"].endswith("@northwind.example.test") for r in rows)
    assert len({r["email"] for r in rows}) == len(rows)
    analytics_header = (root / "people/employees.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "first_name" not in analytics_header and "email" not in analytics_header
