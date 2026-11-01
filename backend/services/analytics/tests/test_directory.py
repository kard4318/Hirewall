# Tests for the HR employee directory: HR-only access, search, records, and no per-person demographics
import csv
from datetime import date

import pytest
from fastapi.testclient import TestClient

from gateway.auth.hr_auth import create_role_token
from gateway.main import create_app
from services.analytics.config import AnalyticsSettings
from services.analytics.reports import AnalyticsService
from services.analytics.repository import PeopleRepository
from services.analytics.tests.test_generator import run as generate
from services.scheduler.service import SchedulingService
from services.scheduler.tests.conversation_harness import make_harness


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path):
    root = generate(tmp_path)
    analytics = AnalyticsService(PeopleRepository(AnalyticsSettings(as_of=date(2026, 11, 1), min_group_size=5,
                                                                    people_dir=root / "people", audit_file=root / "audit.jsonl")))
    harness = make_harness(monkeypatch)
    monkeypatch.setenv("HR_TOKEN_SECRET", "hr-secret-for-directory-tests")
    client = TestClient(create_app(SchedulingService(harness.deps, None, harness.deps.bookings), None, analytics))
    hr = {"Authorization": f"Bearer {create_role_token('hr', harness.deps.clock.now())}"}
    employee = {"Authorization": f"Bearer {create_role_token('employee', harness.deps.clock.now())}"}
    names = list(csv.DictReader((root / "people/directory.csv").open(encoding="utf-8")))
    return client, hr, employee, names


def test_directory_is_hr_only(api) -> None:
    client, _, employee, _ = api
    assert client.get("/api/hr/directory").status_code == 401
    assert client.get("/api/hr/directory", headers=employee).status_code == 401
    assert client.get("/api/hr/directory/E-0001", headers=employee).status_code == 401


def test_search_lists_named_active_employees(api) -> None:
    client, hr, _, names = api
    page = client.get("/api/hr/directory", headers=hr).json()
    assert page["total"] == 400 and len(page["employees"]) == 25 and page["synthetic"] is True
    first = page["employees"][0]
    assert first["name"] and first["email"].endswith("@northwind.example.test") and first["status"] == "active"
    target = names[10]
    found = client.get("/api/hr/directory", params={"q": target["last_name"], "status": "all"}, headers=hr).json()
    assert any(e["employee_id"] == target["employee_id"] for e in found["employees"])
    sales = client.get("/api/hr/directory", params={"department": "Sales"}, headers=hr).json()
    assert sales["total"] == 60 and all(e["department"] == "Sales" for e in sales["employees"])
    left = client.get("/api/hr/directory", params={"status": "left"}, headers=hr).json()
    assert left["total"] == 119


def test_record_has_details_but_no_demographics(api) -> None:
    client, hr, _, _ = api
    leaver = client.get("/api/hr/directory", params={"status": "left"}, headers=hr).json()["employees"][0]
    record = client.get(f"/api/hr/directory/{leaver['employee_id']}", headers=hr).json()
    assert record["name"] == leaver["name"] and record["end_date"] and record["exit_type"]
    assert {"manager", "direct_reports", "training", "tenure_years", "hire_date", "contract", "site"} <= set(record)
    assert "age_band" not in record and "gender" not in record
    assert client.get("/api/hr/directory/E-9999", headers=hr).status_code == 404


def test_analytics_endpoints_still_never_contain_names(api) -> None:
    client, hr, _, names = api
    sample = {n["last_name"] for n in names[:50]} | {n["email"] for n in names[:50]}
    for path in ("summary", "headcount/by?dimension=department", "attrition/by-department", "recap", "training"):
        body = client.get(f"/api/hr/analytics/{path}", headers=hr).text
        assert not any(value in body for value in sample), path
