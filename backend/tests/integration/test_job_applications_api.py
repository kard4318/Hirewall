"""The offer-to-application flow over HTTP: HR import, publish, public apply, HR review, scoped scoring."""
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
from services.screener.tests.pdf_fixtures import minimal_pdf
from services.screener.tests.test_screener_applications import OfferLLM, resume

OFFER = (REPO_ROOT / "data/job_offers/pdf/backend_developer_full_time.pdf").read_bytes()
LETTER = (REPO_ROOT / "data/attacks/applications/letter_visible.pdf").read_bytes()
FORM = {"full_name": "Sam Fictif", "email": "sam@example.test", "consent": "true"}


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


def apply(api, job_id, cv=None, letter=None, **fields):
    files = {"cv": ("cv.pdf", cv or resume("a"))}
    if letter:
        files["cover_letter"] = ("letter.pdf", letter)
    return api.client.post(f"/api/jobs/{job_id}/applications", files=files, data={**FORM, **fields})


def test_full_flow(api):
    job_id, task = draft(api)
    assert task["files"][0]["status"] == "accepted"
    posting = api.client.get(f"/api/screener/jobs/drafts/{job_id}", headers=api.hr).json()
    assert posting["status"] == "draft" and posting["details"]["company"] == "Northwind Labs"
    assert api.client.get("/api/jobs").json() == {"jobs": []}
    assert api.client.get(f"/api/jobs/{job_id}").status_code == 404

    details = {**posting["details"], "title": "Backend Developer (edited)", "required_skills": ["Python", "FastAPI"]}
    edited = api.client.put(f"/api/screener/jobs/{job_id}", json=details, headers=api.hr).json()
    assert {"text": "Experience with FastAPI", "kind": "required"} in edited["requirements"]
    assert api.client.post(f"/api/screener/jobs/{job_id}/publish", headers=api.hr).json()["status"] == "published"

    offers = api.client.get("/api/jobs").json()["jobs"]
    assert [o["job_id"] for o in offers] == [job_id] and offers[0]["details"]["title"].endswith("(edited)")
    assert set(api.client.get(f"/api/jobs/{job_id}").json()) == {"job_id", "published_at", "details"}

    pool = api.client.post("/api/screener/candidates", files=[("files", ("x.pdf", resume("pool")))], headers=api.hr)
    task_done(api, pool.json()["task_id"])

    applied = apply(api, job_id, letter=LETTER)
    assert applied.status_code == 202 and set(applied.json()) == {"reference_id"}
    rows = wait_for(
        lambda: api.client.get(f"/api/screener/jobs/{job_id}/applications", headers=api.hr).json()["applications"],
        lambda r: len(r) == 1,
    )
    row = rows[0]
    assert row["cover_letter"]["availability"] == "January" and row["candidate"]["injection_flag"] is True
    assert row["injection_excerpts"][0].startswith("[cover letter] ")
    assert "Sam Fictif" not in json.dumps(rows) and "sam@example.test" not in json.dumps(rows)

    cv_data = api.client.get(f"/api/screener/candidates/{row['candidate_id']}/extracted", headers=api.hr).json()
    assert cv_data["sections"] and cv_data["profile"]["skills"] == ["Python"]
    identity = api.client.get(f"/api/screener/candidates/{row['candidate_id']}/identity", headers=api.hr).json()
    assert identity["contacts"][0]["email"] == "sam@example.test"

    jobs = {j["job_id"]: j for j in api.client.get("/api/screener/jobs", headers=api.hr).json()["jobs"]}
    assert jobs[job_id]["status"] == "published" and jobs[job_id]["application_count"] == 1

    run_id = api.client.post(f"/api/screener/jobs/{job_id}/runs", headers=api.hr).json()["run_id"]
    run = wait_for(lambda: api.client.get(f"/api/screener/runs/{run_id}", headers=api.hr).json(), lambda r: r["status"] == "done")
    assert [c["candidate_id"] for c in run["candidates"]] == [row["candidate_id"]]

    assert api.client.post(f"/api/screener/jobs/{job_id}/close", headers=api.hr).json()["status"] == "closed"
    assert api.client.get("/api/jobs").json() == {"jobs": []}
    assert api.client.get(f"/api/screener/runs/{run_id}", headers=api.hr).status_code == 200


def test_draft_and_closed_jobs_refuse_applications(api):
    job_id, _ = draft(api)
    response = apply(api, job_id)
    assert response.status_code == 404 and response.json() == {"detail": "job_not_found"}
    api.client.post(f"/api/screener/jobs/{job_id}/publish", headers=api.hr)
    api.client.post(f"/api/screener/jobs/{job_id}/close", headers=api.hr)
    response = apply(api, job_id)
    assert response.status_code == 409 and response.json() == {"detail": "job_closed"}
    assert api.client.get(f"/api/jobs/{job_id}").status_code == 409
    assert apply(api, "job-preset-backend").status_code == 404


@pytest.mark.parametrize(("fields", "code"), [
    ({"consent": "false"}, "consent_required"),
    ({"full_name": " "}, "invalid_name"),
    ({"email": "not-an-email"}, "invalid_email"),
])
def test_form_is_checked(api, fields, code):
    response = apply(api, published(api), **fields)
    assert response.status_code == 422 and response.json() == {"detail": code}


def test_consent_is_required_when_missing(api):
    job_id = published(api)
    data = {key: value for key, value in FORM.items() if key != "consent"}
    response = api.client.post(f"/api/jobs/{job_id}/applications", files={"cv": ("cv.pdf", resume("a"))}, data=data)
    assert response.json() == {"detail": "consent_required"}


def test_cv_is_required_and_bad_files_get_a_reason(api):
    job_id = published(api)
    assert api.client.post(f"/api/jobs/{job_id}/applications", data=FORM, files={"x": ("x", b"y")}).json() == {"detail": "cv_required"}
    assert apply(api, job_id, cv=b"nope").json() == {"detail": "cv_bad_signature"}
    bad_letter = api.client.post(
        f"/api/jobs/{job_id}/applications", data=FORM,
        files={"cv": ("cv.pdf", resume("a")), "cover_letter": ("l.exe", b"MZ")},
    )
    assert bad_letter.status_code == 422 and bad_letter.json() == {"detail": "cover_letter_unsupported_type"}


def test_too_large_body_is_refused_before_parsing(api):
    job_id = published(api)
    response = apply(api, job_id, cv=minimal_pdf(["x"]) + b"0" * (11 * 1024 * 1024))
    assert response.status_code == 413 and response.json() == {"detail": "upload_too_large"}


def test_public_apply_is_rate_limited_apart_from_hr(api):
    job_id = published(api)
    codes = [apply(api, job_id, cv=b"nope").status_code for _ in range(6)]
    assert codes == [422] * 5 + [429]
    assert apply(api, job_id).json() == {"detail": "too_many_applications"}
    upload = api.client.post("/api/screener/candidates", files=[("files", ("a.txt", b"x"))], headers=api.hr)
    assert upload.status_code == 202


def test_public_responses_hold_no_extracted_data(api):
    job_id = published(api)
    body = apply(api, job_id).text
    for word in ("candidate", "score", "cand-", "Python"):
        assert word not in body
    public = api.client.get(f"/api/jobs/{job_id}").json()
    assert "flagged_requirements" not in public and "source_hash" not in public and "status" not in public


def test_hr_upload_attaches_to_the_job(api):
    job_id = published(api)
    response = api.client.post(
        "/api/screener/candidates", files=[("files", ("x.pdf", resume("a")))], data={"job_id": job_id}, headers=api.hr
    )
    task_done(api, response.json()["task_id"])
    rows = api.client.get(f"/api/screener/jobs/{job_id}/applications", headers=api.hr).json()["applications"]
    assert rows[0]["source"] == "hr_upload"
    unknown = api.client.post(
        "/api/screener/candidates", files=[("files", ("x.pdf", resume("a")))], data={"job_id": "nope"}, headers=api.hr
    )
    assert unknown.status_code == 404


def test_edits_on_a_published_job_are_refused(api):
    job_id = published(api)
    response = api.client.put(f"/api/screener/jobs/{job_id}", json={"title": "Late"}, headers=api.hr)
    assert response.status_code == 409 and response.json() == {"detail": "posting_published"}
    extra = api.client.put(f"/api/screener/jobs/{job_id}", json={"title": "x", "evil": 1}, headers=api.hr)
    assert extra.status_code == 422


def test_bad_offer_file_reports_a_reason(api):
    _, task = draft(api, data=b"MZ", name="offer.exe")
    assert task["files"][0]["reason_code"] == "unsupported_type"
