"""The HR offer flow over HTTP: import, edit, publish, attach candidates, scoped scoring. No public routes exist."""
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from core.approval_queue.approval_queue import ApprovalQueue
from gateway.auth.hr_auth import create_role_token
from gateway.main import create_app
from orchestrator.graph import Orchestrator
from orchestrator.record_approval import RecordWorkflow
from services.scheduler.service import SchedulingService
from services.scheduler.tests.conversation_harness import make_harness
from services.screener.node import SCREEN_TASK, screen_job_node
from services.screener.tests.helpers import REPO_ROOT, make_service
from services.screener.tests.test_screener_applications import OfferLLM, resume

OFFER = (REPO_ROOT / "data/job_offers/pdf/backend_developer_full_time.pdf").read_bytes()


def wait_for(read, done, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = read()
        if done(value):
            return value
        time.sleep(0.02)
    raise AssertionError("timed out")


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    service = make_service(tmp_path, OfferLLM(), background=True)
    queue = ApprovalQueue(tmp_path / "queue.sqlite3")
    workflow = RecordWorkflow(service.build_proposed_action, queue, service._audit, service._status_store)
    drafter = SimpleNamespace(
        deps=SimpleNamespace(llm=None, candidates=None, detector=None, phishing_detector=None),
        queue=queue, audit=service._audit,
    )
    orchestrator = Orchestrator(
        workflow=drafter, checkpointer=InMemorySaver(), services={SCREEN_TASK: screen_job_node(service)},
        record_workflow=workflow,
    )
    harness = make_harness(monkeypatch)
    monkeypatch.setenv("HR_TOKEN_SECRET", "hr-secret-for-application-tests")
    client = TestClient(create_app(
        SchedulingService(harness.deps, None, harness.deps.bookings),
        email_orchestrator=orchestrator, screening_service=service,
    ))
    hr = {"Authorization": f"Bearer {create_role_token('hr', harness.deps.clock.now())}"}
    return SimpleNamespace(client=client, hr=hr, service=service)


def task_done(api, task_id):
    return wait_for(
        lambda: api.client.get(f"/api/screener/tasks/{task_id}", headers=api.hr).json(), lambda t: t["status"] == "done"
    )


def draft(api, data=OFFER, name="offer.pdf"):
    started = api.client.post("/api/screener/jobs/extract", files={"file": (name, data)}, headers=api.hr)
    assert started.status_code == 202
    body = started.json()
    return body["job_id"], task_done(api, body["task_id"])


def published(api):
    job_id, _ = draft(api)
    assert api.client.post(f"/api/screener/jobs/{job_id}/publish", headers=api.hr).status_code == 200
    return job_id


def attach(api, job_id, tag="a"):
    data = {"job_id": job_id} if job_id else None
    response = api.client.post(
        "/api/screener/candidates", files=[("files", (f"{tag}.pdf", resume(tag)))], data=data, headers=api.hr
    )
    return response


def test_full_flow(api):
    job_id, task = draft(api)
    assert task["files"][0]["status"] == "accepted"
    posting = api.client.get(f"/api/screener/jobs/drafts/{job_id}", headers=api.hr).json()
    assert posting["status"] == "draft" and posting["details"]["company"] == "Fictional Company"

    details = {**posting["details"], "title": "Backend Developer (edited)", "required_skills": ["Python", "FastAPI"]}
    edited = api.client.put(f"/api/screener/jobs/{job_id}", json=details, headers=api.hr).json()
    assert {"text": "Experience with FastAPI", "kind": "required"} in edited["requirements"]
    assert api.client.post(f"/api/screener/jobs/{job_id}/publish", headers=api.hr).json()["status"] == "published"

    task_done(api, attach(api, None, "pool").json()["task_id"])
    task_done(api, attach(api, job_id, "a").json()["task_id"])
    rows = api.client.get(f"/api/screener/jobs/{job_id}/applications", headers=api.hr).json()["applications"]
    assert len(rows) == 1 and rows[0]["source"] == "hr_upload"

    cv_data = api.client.get(f"/api/screener/candidates/{rows[0]['candidate_id']}/extracted", headers=api.hr).json()
    assert cv_data["sections"] and cv_data["profile"]["skills"] == ["Python"]
    assert "Fictional a" not in json.dumps(cv_data["profile"]["skills"])

    jobs = {j["job_id"]: j for j in api.client.get("/api/screener/jobs", headers=api.hr).json()["jobs"]}
    assert jobs[job_id]["status"] == "published" and jobs[job_id]["application_count"] == 1

    run_id = api.client.post(f"/api/screener/jobs/{job_id}/runs", headers=api.hr).json()["run_id"]
    run = wait_for(lambda: api.client.get(f"/api/screener/runs/{run_id}", headers=api.hr).json(), lambda r: r["status"] == "done")
    assert [c["candidate_id"] for c in run["candidates"]] == [rows[0]["candidate_id"]]

    assert api.client.post(f"/api/screener/jobs/{job_id}/close", headers=api.hr).json()["status"] == "closed"
    assert api.client.get(f"/api/screener/runs/{run_id}", headers=api.hr).status_code == 200


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/api/jobs"), ("get", "/api/jobs/job-x"), ("post", "/api/jobs/job-x/applications"),
])
def test_there_is_no_public_way_in(api, method, path):
    assert getattr(api.client, method)(path).status_code in (404, 405)


def test_published_offer_is_not_public(api):
    job_id = published(api)
    assert api.client.get(f"/api/jobs/{job_id}").status_code == 404
    response = api.client.post(f"/api/jobs/{job_id}/applications", files={"cv": ("cv.pdf", resume("a"))})
    assert response.status_code in (404, 405)
    assert api.service.list_applications(job_id) == []


def test_hr_upload_attaches_only_to_a_real_posting(api):
    assert attach(api, "nope").status_code == 404
    job_id, _ = draft(api)
    response = attach(api, job_id)
    assert response.status_code == 409 and response.json() == {"detail": "posting_draft"}


def test_csv_with_its_files_is_imported_and_attached(api):
    job_id = published(api)
    resumes = REPO_ROOT / "data/resumes"
    files = [
        ("files", ("candidates_sample.csv", (resumes / "candidates_sample.csv").read_bytes())),
        ("files", ("ines_kacem_backend.pdf", (resumes / "cvs/ines_kacem_backend.pdf").read_bytes())),
        ("files", ("walid_saidi_data.pdf", (resumes / "cvs/walid_saidi_data.pdf").read_bytes())),
    ]
    response = api.client.post("/api/screener/candidates", files=files, data={"job_id": job_id}, headers=api.hr)
    assert response.status_code == 202
    task = task_done(api, response.json()["task_id"])
    assert task["total"] == 3 and {f["status"] for f in task["files"]} == {"accepted"}
    rows = api.client.get(f"/api/screener/jobs/{job_id}/applications", headers=api.hr).json()["applications"]
    assert len(rows) == 3 and sum(r["cover_letter"] is not None for r in rows) == 2
    assert "Kacem" not in json.dumps(rows) and "ines.kacem" not in json.dumps(rows)


@pytest.mark.parametrize(("files", "code"), [
    ([("files", ("a.csv", b"name\nA\n"))], "csv_no_cv_column"),
    ([("files", ("a.csv", b""))], "csv_empty"),
    ([("files", ("a.csv", b"cv\na.pdf\n")), ("files", ("b.csv", b"cv\na.pdf\n"))], "one_csv_only"),
])
def test_unusable_csv_gets_a_reason(api, files, code):
    response = api.client.post("/api/screener/candidates", files=files, headers=api.hr)
    assert response.status_code == 422 and response.json() == {"detail": code}


def test_edits_on_a_published_job_are_refused(api):
    job_id = published(api)
    response = api.client.put(f"/api/screener/jobs/{job_id}", json={"title": "Late"}, headers=api.hr)
    assert response.status_code == 409 and response.json() == {"detail": "posting_published"}
    extra = api.client.put(f"/api/screener/jobs/{job_id}", json={"title": "x", "evil": 1}, headers=api.hr)
    assert extra.status_code == 422


def test_bad_offer_file_reports_a_reason(api):
    _, task = draft(api, data=b"MZ", name="offer.exe")
    assert task["files"][0]["reason_code"] == "unsupported_type"
