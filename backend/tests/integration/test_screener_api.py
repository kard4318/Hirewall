"""API tests for the screener and approval routes, with a fake model, hashing embedder and temp storage."""
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
from services.screener.tests.helpers import ATTACK_PDF, FakeLLM, make_service

JOB = "job-preset-backend"


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
    service = make_service(tmp_path, FakeLLM(), background=True)
    queue = ApprovalQueue(tmp_path / "queue.sqlite3")
    workflow = RecordWorkflow(service.build_proposed_action, queue, service._audit, service._status_store)
    drafter = SimpleNamespace(
        deps=SimpleNamespace(llm=None, candidates=None, detector=None, phishing_detector=None),
        queue=queue, audit=service._audit,
    )
    orchestrator = Orchestrator(
        workflow=drafter,
        checkpointer=InMemorySaver(),
        services={SCREEN_TASK: screen_job_node(service)},
        record_workflow=workflow,
    )
    harness = make_harness(monkeypatch)
    monkeypatch.setenv("HR_TOKEN_SECRET", "hr-secret-for-screener-tests")
    client = TestClient(create_app(
        SchedulingService(harness.deps, None, harness.deps.bookings),
        email_orchestrator=orchestrator,
        screening_service=service,
    ))
    hr = {"Authorization": f"Bearer {create_role_token('hr', harness.deps.clock.now())}"}
    return SimpleNamespace(client=client, hr=hr, service=service, tmp_path=tmp_path)


def load_and_score(api):
    task = api.client.post("/api/screener/candidates/demo", headers=api.hr).json()["task_id"]
    wait_for(lambda: api.client.get(f"/api/screener/tasks/{task}", headers=api.hr).json(), lambda t: t["status"] == "done")
    response = api.client.post(f"/api/screener/jobs/{JOB}/runs", headers=api.hr)
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    return wait_for(
        lambda: api.client.get(f"/api/screener/runs/{run_id}", headers=api.hr).json(), lambda r: r["status"] == "done"
    )


@pytest.mark.parametrize(("method", "path"), [
    ("post", "/api/screener/candidates"),
    ("get", "/api/screener/tasks/x"),
    ("get", "/api/screener/candidates"),
    ("post", "/api/screener/candidates/demo"),
    ("get", "/api/screener/jobs"),
    ("post", "/api/screener/jobs"),
    ("post", "/api/screener/jobs/x/runs"),
    ("get", "/api/screener/runs/x"),
    ("post", "/api/screener/runs/x/shortlist-proposals"),
    ("get", "/api/screener/candidates/x/identity"),
    ("post", "/api/screener/jobs/extract"),
    ("get", "/api/screener/jobs/drafts/x"),
    ("put", "/api/screener/jobs/x"),
    ("post", "/api/screener/jobs/x/publish"),
    ("post", "/api/screener/jobs/x/close"),
    ("get", "/api/screener/jobs/x/posting"),
    ("get", "/api/screener/jobs/x/applications"),
    ("get", "/api/screener/candidates/x/extracted"),
    ("get", "/api/hr/approvals"),
    ("post", "/api/hr/approvals/x/decision"),
    ("get", "/api/hr/audit-log"),
])
def test_every_route_needs_hr(api, method, path):
    assert getattr(api.client, method)(path).status_code == 401


def test_upload_reports_each_file_without_names(api):
    files = [("files", ("ines_kacem.pdf", ATTACK_PDF.read_bytes(), "application/pdf")),
             ("files", ("virus.exe", b"MZ", "application/octet-stream"))]
    response = api.client.post("/api/screener/candidates", files=files, headers=api.hr)
    assert response.status_code == 202
    url = f"/api/screener/tasks/{response.json()['task_id']}"
    task = wait_for(lambda: api.client.get(url, headers=api.hr).json(), lambda t: t["status"] == "done")
    assert [f["status"] for f in task["files"]] == ["accepted", "rejected"]
    assert task["files"][0]["injection_flag"] and task["files"][0]["hidden_text_removed"]
    assert task["files"][1]["reason_code"] == "unsupported_type"
    assert "ines" not in str(task).lower()


def test_uploads_are_rate_limited(api):
    files = [("files", ("a.txt", b"x", "text/plain"))]
    codes = [api.client.post("/api/screener/candidates", files=files, headers=api.hr).status_code for _ in range(11)]
    assert codes[:10] == [202] * 10 and codes[10] == 429
    last = api.client.post("/api/screener/candidates", files=files, headers=api.hr)
    assert last.json() == {"detail": "too_many_uploads"}


def test_too_many_files_are_refused(api):
    files = [("files", (f"{i}.pdf", b"x", "application/pdf")) for i in range(21)]
    assert api.client.post("/api/screener/candidates", files=files, headers=api.hr).status_code == 422


def test_jobs_list_and_create(api):
    assert JOB in {j["job_id"] for j in api.client.get("/api/screener/jobs", headers=api.hr).json()["jobs"]}
    body = {"title": "QA Engineer", "requirements": [{"text": "Write tests", "kind": "required"}]}
    created = api.client.post("/api/screener/jobs", json=body, headers=api.hr)
    assert created.status_code == 201 and created.json()["job_id"].startswith("job-")
    assert api.client.post("/api/screener/jobs", json={"title": "x", "requirements": []}, headers=api.hr).status_code == 422


def test_errors_are_short_codes_that_do_not_echo_input(api):
    response = api.client.post("/api/screener/jobs/<script>/runs", headers=api.hr)
    assert response.status_code == 404 and response.json() == {"detail": "job_not_found"}
    assert api.client.get("/api/screener/runs/nope", headers=api.hr).json() == {"detail": "run_not_found"}
    assert api.client.get("/api/screener/tasks/nope", headers=api.hr).status_code == 404


def test_full_flow_from_demo_to_recorded_shortlist(api):
    run = load_and_score(api)
    assert run["total"] == 16 and run["pending"] == [] and len(run["candidates"]) == 16
    first = run["candidates"][0]
    assert first["rank"] == 1 and first["profile"] and first["evidence_chunks"]

    selected = [c["candidate_id"] for c in run["candidates"][:2]]
    url = f"/api/screener/runs/{run['run_id']}/shortlist-proposals"
    created = api.client.post(url, json={"candidate_ids": selected, "kind": "shortlist"}, headers=api.hr)
    assert created.status_code == 201
    proposal = created.json()
    assert proposal["status"] == "awaiting_review"
    assert api.client.get(f"/api/screener/runs/{run['run_id']}", headers=api.hr).json()["statuses"] == {}

    items = api.client.get("/api/hr/approvals?status=pending", headers=api.hr).json()["items"]
    assert [i["approval_id"] for i in items] == [proposal["approval_id"]]
    assert items[0]["action_type"] == "record_shortlist"
    assert items[0]["summary"]["candidate_ids"] == sorted(selected)

    decision_url = f"/api/hr/approvals/{proposal['approval_id']}/decision"
    assert api.client.post(decision_url, json={"action": "approve"}, headers=api.hr).status_code == 422
    stale = api.client.post(decision_url, json={"action": "approve", "reviewed_hash": "0" * 64}, headers=api.hr).json()
    assert stale["waiting_for_human"] and stale["reason_code"] == "not_pending_or_text_changed"
    done = api.client.post(
        decision_url, json={"action": "approve", "reviewed_hash": proposal["payload_hash"]}, headers=api.hr
    )
    assert done.status_code == 200 and done.json()["status"] == "recorded"
    again = api.client.post(
        decision_url, json={"action": "approve", "reviewed_hash": proposal["payload_hash"]}, headers=api.hr
    )
    assert again.status_code == 409 and again.json()["detail"] == "not_awaiting_review"

    statuses = api.client.get(f"/api/screener/runs/{run['run_id']}", headers=api.hr).json()["statuses"]
    assert statuses == {cid: "shortlisted" for cid in selected}
    audit = api.client.get("/api/hr/audit-log", headers=api.hr).json()
    assert audit["verified"]
    outcome = next(e for e in audit["entries"] if e["event"] == "executor.outcome")
    assert outcome["fields"]["status"] == "recorded" and outcome["fields"]["approver"] == "HR desk"


def test_proposals_for_different_candidates_all_stay_pending(api):
    run = load_and_score(api)
    url = f"/api/screener/runs/{run['run_id']}/shortlist-proposals"
    first, second = (c["candidate_id"] for c in run["candidates"][:2])
    a = api.client.post(url, json={"candidate_ids": [first], "kind": "shortlist"}, headers=api.hr).json()
    b = api.client.post(url, json={"candidate_ids": [second], "kind": "shortlist"}, headers=api.hr).json()
    c = api.client.post(url, json={"candidate_ids": [second], "kind": "rejection"}, headers=api.hr).json()
    pending = {i["approval_id"] for i in api.client.get("/api/hr/approvals?status=pending", headers=api.hr).json()["items"]}
    assert pending == {a["approval_id"], b["approval_id"], c["approval_id"]}
    for proposal in (a, b):
        decision = {"action": "approve", "reviewed_hash": proposal["payload_hash"]}
        url2 = f"/api/hr/approvals/{proposal['approval_id']}/decision"
        assert api.client.post(url2, json=decision, headers=api.hr).json()["status"] == "recorded"
    statuses = api.client.get(f"/api/screener/runs/{run['run_id']}", headers=api.hr).json()["statuses"]
    assert statuses == {first: "shortlisted", second: "shortlisted"}


def test_client_cannot_set_the_reviewer(api):
    response = api.client.post(
        "/api/hr/approvals/x/decision", json={"action": "reject", "reviewer": "Someone"}, headers=api.hr
    )
    assert response.status_code == 422


def test_proposal_for_unknown_candidates_is_refused(api):
    run = load_and_score(api)
    url = f"/api/screener/runs/{run['run_id']}/shortlist-proposals"
    response = api.client.post(url, json={"candidate_ids": ["cand-x"], "kind": "shortlist"}, headers=api.hr)
    assert response.status_code == 409 and response.json() == {"detail": "unknown_candidate"}


def test_identity_is_revealed_only_on_request_and_audited(api):
    run = load_and_score(api)
    candidate_id = run["candidates"][0]["candidate_id"]
    assert not [e for e in api.client.get("/api/hr/audit-log", headers=api.hr).json()["entries"]
                if e["event"] == "screener.identity_revealed"]
    response = api.client.get(f"/api/screener/candidates/{candidate_id}/identity", headers=api.hr)
    assert response.status_code == 200 and response.json()["candidate_id"] == candidate_id
    events = [e for e in api.client.get("/api/hr/audit-log", headers=api.hr).json()["entries"]
              if e["event"] == "screener.identity_revealed"]
    assert events[0]["fields"] == {"candidate_id": candidate_id, "reviewer": "HR desk"}
    assert api.client.get("/api/screener/candidates/nope/identity", headers=api.hr).status_code == 404


def test_candidates_list_is_pseudonymous(api):
    run = load_and_score(api)
    rows = api.client.get("/api/screener/candidates", headers=api.hr).json()["candidates"]
    assert len(rows) == run["total"]
    assert "Amira" not in str(rows) and all(r["candidate_id"].startswith("cand-") for r in rows)
