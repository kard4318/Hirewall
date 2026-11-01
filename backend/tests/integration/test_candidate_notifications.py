"""After approval only: rejected candidates get an email, shortlisted ones an invitation from the Scheduler bot."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from core.approval_queue.approval_queue import ApprovalQueue, action_hash
from core.candidate_status.store import CandidateStatusStore
from core.audit.audit_log import AuditLog
from core.executor.executor import execute_record
from core.integrations.email_provider import EmailDeliveryError, OutboxEmailSender
from gateway.auth.hr_auth import create_role_token
from gateway.candidate_notifier import REJECTION_SUBJECT, CandidateNotifier, scheduler_id
from gateway.main import create_app
from orchestrator.graph import Orchestrator
from orchestrator.record_approval import RecordWorkflow
from services.scheduler.conversation.adapters.screener_handoff import ScreenerHandoff
from services.scheduler.conversation.adapters.screener_mock import ScreenerCandidateRepo
from services.scheduler.scheduling_state import SchedulingStateStore
from services.scheduler.service import SchedulingService
from services.scheduler.tests.conversation_harness import make_harness
from services.screener.models import ApplicantContact
from services.screener.node import SCREEN_TASK, screen_job_node
from services.screener.tests.helpers import make_service
from services.screener.tests.pdf_fixtures import minimal_pdf
from services.screener.tests.test_screener_applications import OfferLLM

JOB = "job-preset-backend"
REVIEWER = "HR desk"


def cv(name, email):
    lines = [name, "Backend Developer"]
    if email:
        lines.append(f"Email: {email}")
    return minimal_pdf([*lines, "EXPERIENCE", f"Developer at {name} Fictional Co (2019 - 2025)", "Built Python REST APIs."])


class Recorder(OutboxEmailSender):
    pass


class SmtpLike(OutboxEmailSender):
    mode = "smtp"


class Broken(OutboxEmailSender):
    mode = "smtp"

    def send(self, to, subject, body):
        raise EmailDeliveryError("SMTP delivery failed (OSError)")


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    service = make_service(tmp_path, OfferLLM())
    harness = make_harness(monkeypatch)
    scheduling_mail = Recorder()
    harness.deps.email = scheduling_mail
    handoff = ScreenerHandoff(tmp_path / "handoff.json")
    state = SchedulingStateStore(tmp_path / "scheduling_state.json")
    harness.deps.bookings = state
    harness.deps.candidates = ScreenerCandidateRepo(handoff, state)
    scheduling = SchedulingService(harness.deps, handoff, state, public_base_url="https://hire.example")
    mail = Recorder()
    notifier = CandidateNotifier(service, scheduling, mail)
    queue = ApprovalQueue(tmp_path / "queue.sqlite3")
    task = service.ingest_files([
        ("a.pdf", cv("Ines Kacem", "ines@example.test")),
        ("b.pdf", cv("Walid Saidi", "walid@example.test")),
        ("c.pdf", cv("Sami Fictif", None)),
    ])
    assert {f.status for f in task.files} == {"accepted"}
    run = service.execute_run(service.start_run(JOB).run_id)
    return SimpleNamespace(
        service=service, scheduling=scheduling, scheduling_mail=scheduling_mail, mail=mail, notifier=notifier, queue=queue,
        run=run, audit=service._audit, status=service._status_store, handoff=handoff, tmp_path=tmp_path,
        harness=harness, ids={f.candidate_id: f for f in task.files}, by_name=[f.candidate_id for f in task.files],
    )


def decide(world, action_type, candidate_ids, key="p1", notifier=None):
    payload = {"job_id": JOB, "run_id": world.run.run_id, "candidate_ids": sorted(candidate_ids)}
    item = world.queue.submit({
        "action_type": action_type, "payload": payload, "in_reply_to": f"{action_type}:{JOB}:{key}",
        "payload_hash": action_hash(action_type, payload), "idempotency_key": key,
    }, "t")
    world.queue.approve(item.id, REVIEWER, item.payload_hash)
    return execute_record(
        item.id, queue=world.queue, status_store=world.status, audit=world.audit,
        notifier=notifier if notifier is not None else world.notifier,
    )


def notifications(world):
    return {e["fields"]["candidate_id"]: e["fields"]["outcome"] for e in world.audit.entries()
            if e["event"] == "executor.notification"}


def test_rejection_emails_the_address_in_the_cv(world):
    ines = world.by_name[0]
    assert decide(world, "record_rejection", [ines]).status == "recorded"
    message = world.mail.outbox[0]
    assert message["to"] == "ines@example.test"
    assert message["subject"] == REJECTION_SUBJECT.format(job_title="Backend Python Developer", company="Northwind Labs")
    assert message["body"].startswith("Hello Ines,")
    assert notifications(world) == {ines: "outbox"}
    assert world.status.statuses_for(JOB) == {ines: "rejected"}
    assert world.scheduling_mail.outbox == []


def test_rejection_gives_no_score_or_reason(world):
    decide(world, "record_rejection", [world.by_name[0]])
    body = world.mail.outbox[0]["body"].casefold()
    for word in ("score", "%", "rank", "injection", "model"):
        assert word not in body


def test_shortlist_invites_through_the_scheduler_bot(world):
    ines = world.by_name[0]
    assert decide(world, "record_shortlist", [ines]).status == "recorded"
    message = world.scheduling_mail.outbox[0]
    assert message["to"] == "ines@example.test" and "Backend Python Developer" in message["subject"]
    assert "https://hire.example/candidate?token=" in message["body"] and "Ines" in message["body"]
    assert world.mail.outbox == []
    scheduler = scheduler_id(ines, JOB)
    assert world.scheduling.state.status(scheduler) == "invited"
    assert notifications(world) == {ines: "outbox"}
    token = world.scheduling.links[scheduler].split("token=")[1]
    from urllib.parse import unquote

    assert world.scheduling.check_link(unquote(token))["job_title"] == "Backend Python Developer"


def test_shortlisted_candidate_appears_on_the_hr_scheduling_page(world):
    ines = world.by_name[0]
    decide(world, "record_shortlist", [ines])
    assert JOB in {job["job_id"] for job in world.scheduling.jobs()}
    rows = world.scheduling.candidates(JOB)
    row = next(r for r in rows if r["candidate_id"] == scheduler_id(ines, JOB))
    assert row["status"] == "invited" and row["first_name"] == "Ines" and row["last_name"] == "Kacem"


def test_nothing_goes_out_before_approval(world):
    payload = {"job_id": JOB, "run_id": world.run.run_id, "candidate_ids": [world.by_name[0]]}
    item = world.queue.submit({
        "action_type": "record_rejection", "payload": payload, "in_reply_to": "x",
        "payload_hash": action_hash("record_rejection", payload), "idempotency_key": "k",
    }, "t")
    result = execute_record(item.id, queue=world.queue, status_store=world.status, audit=world.audit, notifier=world.notifier)
    assert result.status == "refused"
    assert world.mail.outbox == [] and notifications(world) == {}


def test_no_address_in_the_cv_is_reported(world):
    sami = world.by_name[2]
    decide(world, "record_rejection", [sami])
    assert world.mail.outbox == [] and notifications(world) == {sami: "no_email"}
    assert world.status.statuses_for(JOB) == {sami: "rejected"}


def form_contact(world, email):
    return ApplicantContact(reference_id=f"ref-{email}", job_id=JOB, full_name="Typed Name", email=email, consent_at="now")


def test_form_address_never_replaces_the_one_in_the_cv(world):
    ines, sami = world.by_name[0], world.by_name[2]
    world.service._identity.add_contact(ines, form_contact(world, "typed@example.test"))
    world.service._identity.add_contact(sami, form_contact(world, "sami-form@example.test"))
    assert world.service.decision_contact(world.run.run_id, ines, "rejection")["email"] == "ines@example.test"
    assert world.service.decision_contact(world.run.run_id, sami, "rejection")["email"] == "sami-form@example.test"


def test_smtp_failure_keeps_the_decision_and_reports_it(world):
    world.notifier._email = Broken()
    ines = world.by_name[0]
    assert decide(world, "record_rejection", [ines]).status == "recorded"
    assert notifications(world) == {ines: "failed"}
    assert world.queue.get("p1").status == "recorded"


def test_invitation_failure_is_reported_and_keeps_the_link(world):
    world.scheduling.deps.email = Broken()
    ines = world.by_name[0]
    decide(world, "record_shortlist", [ines])
    assert notifications(world) == {ines: "failed"}
    assert world.scheduling.state.status(scheduler_id(ines, JOB)) == "invited"
    assert world.scheduling.links[scheduler_id(ines, JOB)]


def test_real_delivery_is_reported_as_sent(world):
    world.notifier._email = SmtpLike()
    ines = world.by_name[0]
    decide(world, "record_rejection", [ines])
    assert notifications(world) == {ines: "sent"}


def test_one_failure_does_not_stop_the_others(world):
    class Flaky(CandidateNotifier):
        def notify(self, action_type, payload, candidate_id):
            if candidate_id == world.by_name[0]:
                raise RuntimeError("private detail")
            return super().notify(action_type, payload, candidate_id)

    flaky = Flaky(world.service, world.scheduling, world.mail)
    decide(world, "record_rejection", world.by_name[:2], notifier=flaky)
    assert notifications(world) == {world.by_name[0]: "failed", world.by_name[1]: "outbox"}
    assert "private detail" not in (world.tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_same_decision_is_not_sent_twice(world):
    ines, walid = world.by_name[:2]
    decide(world, "record_rejection", [ines], key="p1")
    decide(world, "record_rejection", [ines, walid], key="p2")
    assert sorted(m["to"] for m in world.mail.outbox) == ["ines@example.test", "walid@example.test"]


def test_rejecting_a_shortlisted_candidate_withdraws_the_link(world):
    ines = world.by_name[0]
    decide(world, "record_shortlist", [ines], key="p1")
    scheduler = scheduler_id(ines, JOB)
    token = world.scheduling.links[scheduler].split("token=")[1]
    decide(world, "record_rejection", [ines], key="p2")
    assert world.mail.outbox[0]["to"] == "ines@example.test"
    assert scheduler not in world.scheduling.links and world.handoff.find(scheduler) is None
    from urllib.parse import unquote

    from services.scheduler.service import LinkError

    with pytest.raises(LinkError):
        world.scheduling.check_link(unquote(token))


def test_contact_lookup_is_audited_without_the_address(world):
    decide(world, "record_rejection", [world.by_name[0]])
    event = next(e for e in world.audit.entries() if e["event"] == "screener.contact_used")
    assert event["fields"] == {"candidate_id": world.by_name[0], "run_id": world.run.run_id, "purpose": "rejection"}
    log = (world.tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "ines@example.test" not in log and "Kacem" not in log


def test_handoff_survives_a_restart(world):
    decide(world, "record_shortlist", [world.by_name[0]])
    again = ScreenerHandoff(world.tmp_path / "handoff.json")
    assert again.find(scheduler_id(world.by_name[0], JOB)).email == "ines@example.test"
    assert any(j.job_id == "job-be" for j in again.list_jobs())


def test_same_person_on_two_jobs_has_two_scheduler_ids():
    assert scheduler_id("cand-a", "job-1") != scheduler_id("cand-a", "job-2")


def test_mock_candidate_invite_survives_a_mail_failure(world):
    world.scheduling.deps.email = Broken()
    candidate = world.handoff.list_passed("job-be")[0]
    assert world.scheduling.invite(candidate.candidate_id).startswith("/candidate?token=")


def test_decision_route_reports_what_happened(world, monkeypatch):
    queue = world.queue
    workflow = RecordWorkflow(world.service.build_proposed_action, queue, world.audit, world.status, world.notifier)
    drafter = SimpleNamespace(deps=SimpleNamespace(llm=None, candidates=None, detector=None), queue=queue, audit=world.audit)
    orchestrator = Orchestrator(
        workflow=drafter, checkpointer=InMemorySaver(), services={SCREEN_TASK: screen_job_node(world.service)},
        record_workflow=workflow,
    )
    monkeypatch.setenv("HR_TOKEN_SECRET", "hr-secret-for-notification-tests")
    client = TestClient(create_app(world.scheduling, email_orchestrator=orchestrator, screening_service=world.service))
    hr = {"Authorization": f"Bearer {create_role_token('hr', world.harness.deps.clock.now())}"}

    url = f"/api/screener/runs/{world.run.run_id}/shortlist-proposals"
    proposal = client.post(url, json={"candidate_ids": world.by_name, "kind": "rejection"}, headers=hr).json()
    pending = client.get("/api/hr/approvals?status=pending", headers=hr).json()
    assert pending["delivery"] == "outbox" and pending["items"][0]["notifications"] == []
    assert world.mail.outbox == []

    client.post(f"/api/hr/approvals/{proposal['approval_id']}/decision",
                json={"action": "approve", "reviewed_hash": proposal["payload_hash"]}, headers=hr)
    item = client.get("/api/hr/approvals", headers=hr).json()["items"][0]
    outcomes = {n["candidate_id"]: n["outcome"] for n in item["notifications"]}
    assert outcomes == {world.by_name[0]: "outbox", world.by_name[1]: "outbox", world.by_name[2]: "no_email"}
    assert len(world.mail.outbox) == 2
    assert "ines@example.test" not in json.dumps(item)
