# API tests for the recruiter inbox routes over the drafter/classifier orchestrator (scripted model, temp storage)
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gateway.auth.hr_auth import create_role_token
from gateway.main import create_app
from services.scheduler.service import SchedulingService
from services.scheduler.tests.conversation_harness import make_harness

from .test_orchestrator import BODY, EMAIL, Setup, reply
from .test_orchestrator_triage import label


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def build(*responses: object):
        setup = Setup(tmp_path, *responses)
        harness = make_harness(monkeypatch)
        monkeypatch.setenv("HR_TOKEN_SECRET", "hr-secret-for-inbox-tests")
        client = TestClient(create_app(SchedulingService(harness.deps, None, harness.deps.bookings),
                                       email_orchestrator=setup.orchestrator))
        hr = {"Authorization": f"Bearer {create_role_token('hr', harness.deps.clock.now())}"}
        return client, hr, setup
    return build


def test_inbox_requires_hr(api) -> None:
    client, _, setup = api()
    for method, path in (("get", "/api/hr/inbox"), ("get", "/api/hr/inbox/sent"), ("get", f"/api/hr/inbox/{EMAIL}"),
                         ("post", f"/api/hr/inbox/{EMAIL}/draft"), ("post", f"/api/hr/inbox/{EMAIL}/decision")):
        assert getattr(client, method)(path).status_code == 401, path
    setup.close()


def test_list_and_detail(api) -> None:
    client, hr, setup = api()
    rows = client.get("/api/hr/inbox", headers=hr).json()
    assert any(r["email_id"] == EMAIL for r in rows)
    row = next(r for r in rows if r["email_id"] == EMAIL)
    assert row["draft_status"] == "not_started" and not row["waiting_for_human"] and row["subject"]
    detail = client.get(f"/api/hr/inbox/{EMAIL}", headers=hr).json()
    assert detail["email"]["email_id"] == EMAIL and detail["pending_draft"] is None
    assert client.get("/api/hr/inbox/nope", headers=hr).status_code == 404
    setup.close()


def test_draft_then_approve_sends_the_reviewed_text(api) -> None:
    client, hr, setup = api(reply())
    view = client.post(f"/api/hr/inbox/{EMAIL}/draft", headers=hr).json()
    assert view["waiting_for_human"] and client.get("/api/hr/inbox/sent", headers=hr).json() == []
    draft = client.get(f"/api/hr/inbox/{EMAIL}", headers=hr).json()["pending_draft"]
    assert draft["body"] == BODY and draft["payload_hash"]
    url = f"/api/hr/inbox/{EMAIL}/decision"
    assert client.post(url, json={"action": "approve"}, headers=hr).status_code == 422
    assert client.post(url, json={"action": "approve", "reviewed_hash": "0" * 64}, headers=hr).json()["status"] != "sent"
    done = client.post(url, json={"action": "approve", "reviewed_hash": draft["payload_hash"]}, headers=hr).json()
    assert done["status"] == "sent"
    sent = client.get("/api/hr/inbox/sent", headers=hr).json()
    assert len(sent) == 1 and sent[0]["body"] == BODY
    assert client.post(url, json={"action": "reject"}, headers=hr).status_code == 409  # nothing waiting any more
    setup.close()


def test_reject_sends_nothing(api) -> None:
    client, hr, setup = api(reply())
    client.post(f"/api/hr/inbox/{EMAIL}/draft", headers=hr)
    result = client.post(f"/api/hr/inbox/{EMAIL}/decision", json={"action": "reject"}, headers=hr).json()
    assert result["status"] == "rejected" and client.get("/api/hr/inbox/sent", headers=hr).json() == []
    setup.close()


def test_triage_classifies_then_drafts(api) -> None:
    client, hr, setup = api(label(), reply())
    view = client.post(f"/api/hr/inbox/{EMAIL}/triage", headers=hr).json()
    assert view["classification"]["type"] == "candidate_question" and view["waiting_for_human"]
    row = next(r for r in client.get("/api/hr/inbox", headers=hr).json() if r["email_id"] == EMAIL)
    assert row["waiting_for_human"] and row["classification"]["type"] == "candidate_question"
    setup.close()
