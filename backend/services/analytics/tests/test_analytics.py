# Tests for People Analytics: formulas on a hand-built fixture, privacy suppression, rules, stories, auth, isolation
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gateway.auth.hr_auth import create_role_token
from gateway.main import create_app
from services.analytics import metrics
from services.analytics.config import AnalyticsSettings
from services.analytics.privacy import suppress_groups
from services.analytics.reports import AnalyticsService, Query
from services.analytics.repository import PeopleRepository
from services.scheduler.service import SchedulingService
from services.scheduler.tests.conversation_harness import make_harness
from services.analytics.tests.test_generator import run as generate

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parents[4]
AS_OF = date(2026, 7, 1)


def service(min_size: int = 5, folder: Path = FIXTURES, as_of: date = AS_OF) -> AnalyticsService:
    return AnalyticsService(PeopleRepository(AnalyticsSettings(as_of=as_of, min_group_size=min_size, people_dir=folder,
                                                               audit_file=folder / "audit.jsonl")))


def employees() -> list:
    return service().repo.employees()


# --- formulas, checked against values worked out by hand ------------------------------------------------

def test_headcount_formula() -> None:
    people = employees()
    assert metrics.headcount(people, date(2026, 1, 1)) == 13
    assert metrics.headcount(people, date(2026, 3, 31)) == 12      # E-0008 and E-0014 have left
    assert metrics.headcount(people, date(2026, 5, 20)) == 10      # end_date == D means already gone
    assert metrics.headcount(people, date(2026, 5, 19)) == 11
    assert metrics.headcount(people, AS_OF) == 10


def test_attrition_formulas() -> None:
    people = employees()
    assert metrics.attrition_rate(people, date(2026, 1, 1), date(2026, 3, 31)) == pytest.approx(2 / 12.5)
    assert metrics.attrition_rate(people, date(2026, 4, 1), date(2026, 6, 30)) == pytest.approx(2 / 11)
    assert metrics.attrition_rate_12m(people, AS_OF) == pytest.approx(4 / 11.5)  # 13 a year ago, 10 now
    assert metrics.voluntary_share(metrics.exits(people, date(2025, 7, 1), AS_OF)) == pytest.approx(0.75)


def test_tenure_formula() -> None:
    # 912+912+760+546+546+395+167 (Engineering) + 912+912+546 (Support) = 6608 days over 10 people
    assert metrics.avg_tenure_years(employees(), AS_OF) == pytest.approx(660.8 / 365.25)


def test_summary_tiles_and_filters() -> None:
    tiles = service(min_size=3).summary(Query())["tiles"]
    # Period is 2025-07-01..2026-07-01; the previous one ends 2025-06-30, when 9 + 4 people were employed.
    assert tiles["headcount"] == {"value": 10, "previous": 13, "delta": -3}
    assert tiles["exits"]["value"] == 4 and tiles["open_roles"]["value"] == 1
    # Last 28 days: 5 screenings x6 + 2 bookings x4 + 1 approval x1 + 1 answered question x3 = 42 minutes
    assert tiles["hours_saved_estimate"]["value"] == 0.7
    engineering = service().summary(Query(department="Engineering"))["tiles"]
    assert engineering["headcount"]["value"] == 7
    assert service().summary(Query(department="Support"))["tiles"]["headcount"] == {"suppressed": True}


# --- privacy -------------------------------------------------------------------------------------------

def test_small_groups_are_suppressed() -> None:
    groups = [{"key": "a", "n": 8}, {"key": "b", "n": 7}, {"key": "c", "n": 6}, {"key": "d", "n": 2}, {"key": "e", "n": 3}]
    result = {g["key"]: g for g in suppress_groups(groups, 5)}
    assert result["d"] == {"key": "d", "suppressed": True} and result["e"] == {"key": "e", "suppressed": True}
    assert result["a"]["n"] == 8 and result["c"]["n"] == 6  # two hidden groups: no single value can be derived


def test_derivation_by_subtraction_is_prevented() -> None:
    two = suppress_groups([{"key": "big", "n": 40}, {"key": "small", "n": 3}], 5)
    assert all(g.get("suppressed") for g in two)
    three = {g["key"]: g for g in suppress_groups([{"key": "a", "n": 9}, {"key": "b", "n": 6}, {"key": "c", "n": 2}], 5)}
    assert three["c"].get("suppressed") and three["b"].get("suppressed") and three["a"]["n"] == 9


def test_group_endpoint_applies_suppression() -> None:
    departments = service().headcount_by(Query(), "department")
    assert departments["total"] == {"n": 10}
    assert [g.get("suppressed") for g in departments["groups"]] == [True, True]  # 7 and 3: both hidden
    visible = service(min_size=3).headcount_by(Query(), "department")["groups"]
    assert [(g["key"], g["n"]) for g in visible] == [("Engineering", 7), ("Support", 3)]


def test_heatmap_cells_are_suppressed_when_small() -> None:
    report = service().attrition_by_department(Query(start=date(2026, 1, 1)))
    support = next(r for r in report["matrix"] if r["department"] == "Support")
    assert all(cell.get("suppressed") for cell in support["cells"])
    engineering = next(r for r in report["matrix"] if r["department"] == "Engineering")
    q2 = next(c for c in engineering["cells"] if c["quarter"] == "2026Q2")
    assert q2["rate"] == pytest.approx(2 / 8) and q2["n"] == 8


# --- recap and highlights ------------------------------------------------------------------------------

def test_recap_sentences_from_templates() -> None:
    recap = service().weekly_recap(date(2026, 6, 24), Query())
    assert recap["week_start"] == "2026-06-22" and recap["hours_saved"] == 0.6
    assert recap["sentences"][0] == "4 resumes screened, 0 shortlisted and 2 interviews booked."
    assert "HR made 1 approval decision: 1 approved, 0 edited and 0 rejected." in recap["sentences"]
    assert any("answered 1 of 2 employee questions; 1 were passed" in s for s in recap["sentences"])


def test_highlights_fire_only_when_rules_hold_and_carry_numbers() -> None:
    notes = {h["rule"]: h for h in service().weekly_recap(None, Query())["highlights"]}
    spike = notes["attrition_spike"]["numbers"]
    assert spike["department"] == "Engineering" and spike["quarter"] == "2026Q2"
    assert spike["rate"] == pytest.approx(0.25) and spike["ratio"] > 2 and spike["n"] >= 5
    assert notes["engagement_drop"]["numbers"]["drop"] == pytest.approx(0.5)
    assert "training_gap" not in notes  # Support is far below, but only 3 people: rule needs at least 5
    assert all(h["numbers"] and h["rule_text"] for h in notes.values())
    assert "training_gap" in {h["rule"] for h in service(min_size=3).weekly_recap(None, Query())["highlights"]}


def test_highlight_does_not_fire_when_the_drop_is_small(tmp_path: Path) -> None:
    folder = tmp_path / "people"
    shutil.copytree(FIXTURES, folder)
    text = (folder / "engagement.csv").read_text(encoding="utf-8").replace("2026Q2,Engineering,Tunis,3.5", "2026Q2,Engineering,Tunis,3.7")
    (folder / "engagement.csv").write_text(text, encoding="utf-8")
    rules = {h["rule"] for h in service(folder=folder).weekly_recap(None, Query())["highlights"]}
    assert "engagement_drop" not in rules and "attrition_spike" in rules


# --- planted stories on the generated data -------------------------------------------------------------

@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> AnalyticsService:
    root = generate(tmp_path_factory.mktemp("gen"))
    return AnalyticsService(PeopleRepository(AnalyticsSettings(as_of=date(2026, 11, 1), min_group_size=5,
                                                               people_dir=root / "people", audit_file=root / "audit.jsonl")))


def test_story_support_attrition_spike(generated: AnalyticsService) -> None:
    people = generated.repo.employees()
    support = metrics.filter_employees(people, department="Support")
    q2 = metrics.attrition_rate(support, *metrics.quarter_bounds("2026Q2"))
    assert q2 > 2.5 * metrics.company_quarterly_average(people, "2026Q3")
    reasons = [e.exit_reason for e in metrics.exits(support, *metrics.quarter_bounds("2026Q2"))]
    assert reasons.count("career_growth") > len(reasons) / 2


def test_story_engineering_most_stable(generated: AnalyticsService) -> None:
    departments = {d["key"]: d for d in generated.attrition_by_department(Query())["departments"]}
    assert min(departments, key=lambda k: departments[k]["rate"]) == "Engineering"
    people = generated.repo.employees()
    tenure = {d: metrics.avg_tenure_years(metrics.filter_employees(people, department=d), date(2026, 11, 1)) for d in departments}
    assert max(tenure, key=tenure.get) == "Engineering"


def test_story_sales_training_gap(generated: AnalyticsService) -> None:
    rows = {d["key"]: d["completion"] for d in generated.training(Query())["departments"]}
    assert rows["Sales"] < 0.5 and all(v > 0.75 for k, v in rows.items() if k != "Sales")


# --- API: auth and no individual data ------------------------------------------------------------------

ENDPOINTS = ["filters", "summary", "headcount/timeseries", "headcount/by?dimension=department", "headcount/by?dimension=gender",
             "headcount/by?dimension=age_band", "headcount/by?dimension=tenure_band", "attrition/quarterly",
             "attrition/by-department", "attrition/exit-reasons", "engagement", "training", "agent-activity", "recap"]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, generated: AnalyticsService):
    harness = make_harness(monkeypatch)  # sets SCHEDULER_TOKEN_SECRET; analytics needs HR auth only
    monkeypatch.setenv("HR_TOKEN_SECRET", "hr-secret-for-analytics-tests")
    svc = SchedulingService(harness.deps, None, harness.deps.bookings)  # screener unused by these routes
    client = TestClient(create_app(svc, None, generated))
    return client, harness


def test_routes_require_hr_auth(api) -> None:
    client, harness = api
    now = harness.deps.clock.now()
    for path in ENDPOINTS:
        assert client.get(f"/api/hr/analytics/{path}").status_code == 401, path
        assert client.get(f"/api/hr/analytics/{path}", headers={"Authorization": f"Bearer {harness.token}"}).status_code == 401
        employee = create_role_token("employee", now)
        assert client.get(f"/api/hr/analytics/{path}", headers={"Authorization": f"Bearer {employee}"}).status_code == 401


def test_responses_never_contain_individuals(api) -> None:
    client, harness = api
    headers = {"Authorization": f"Bearer {create_role_token('hr', harness.deps.clock.now())}"}
    for path in ENDPOINTS:
        response = client.get(f"/api/hr/analytics/{path}", headers=headers)
        assert response.status_code == 200, (path, response.text)
        body = response.text
        assert "as_of" in response.json(), path
        assert not re.search(r"E-\d{4}", body) and "manager_id" not in body and "employee_id" not in body, path
    assert client.get("/api/hr/analytics/headcount/by?dimension=ethnicity", headers=headers).status_code == 422
    assert client.get("/api/hr/analytics/summary?department=Nope", headers=headers).status_code == 422


# --- isolation: screening never touches analytics or demographics -------------------------------------

def test_screener_never_imports_analytics_or_reads_demographics() -> None:
    screener = REPO / "backend" / "services" / "screener"
    sources = {p: p.read_text(encoding="utf-8") for p in screener.rglob("*.py")}
    assert sources  # the package exists
    for path, text in sources.items():
        assert not re.search(r"^\s*(from|import)\s+(services\.)?analytics\b", text, re.MULTILINE), path
        assert "age_band" not in text and "gender" not in text, path
    for candidate in json.loads((REPO / "data" / "screener_mock" / "candidates.json").read_text(encoding="utf-8")):
        assert not {"age", "age_band", "gender", "date_of_birth"} & set(candidate)
