"""Shortlist workflow through the real graph: proposal, pause, approval, executor, audit."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from core.approval_queue.approval_queue import ApprovalError, ApprovalQueue, action_hash, proposal_hash
from core.audit.audit_log import AuditLog
from core.candidate_status.store import CandidateStatusStore
from core.executor.executor import execute_approved, execute_record
from orchestrator.graph import Orchestrator
from orchestrator.record_approval import RECORD_TASK, RecordWorkflow

PAYLOAD = {"job_id": "job-1", "run_id": "run-1", "candidate_ids": ["cand-a", "cand-b"]}
REVIEWER = "HR desk"


def action(payload=PAYLOAD, action_type="record_shortlist", key="p1"):
    return {
        "action_type": action_type, "payload": payload, "in_reply_to": f"{action_type}:{payload['job_id']}",
        "payload_hash": action_hash(action_type, payload), "idempotency_key": key,
    }


@pytest.fixture
def setup(tmp_path: Path) -> SimpleNamespace:
    queue = ApprovalQueue(tmp_path / "queue.sqlite3")
    audit = AuditLog(tmp_path / "audit.jsonl")
    store = CandidateStatusStore(tmp_path / "status.sqlite3")
    actions = {"p1": action(), "p2": action(action_type="record_rejection", key="p2"),
               "p3": action({**PAYLOAD, "candidate_ids": ["cand-c"]}, key="p3")}
    workflow = RecordWorkflow(build_action=actions.__getitem__, queue=queue, audit=audit, status_store=store)
    drafter = SimpleNamespace(deps=SimpleNamespace(llm=None, candidates=None, detector=None), queue=queue, audit=audit)
    orchestrator = Orchestrator(workflow=drafter, checkpointer=InMemorySaver(), record_workflow=workflow)
    return SimpleNamespace(queue=queue, audit=audit, store=store, orchestrator=orchestrator)


def approve(payload_hash):
    return {"action": "approve", "reviewer": REVIEWER, "reviewed_hash": payload_hash}


def test_action_hash_ignores_key_order_and_covers_the_action():
    assert action_hash("a", {"x": 1, "y": 2}) == action_hash("a", {"y": 2, "x": 1})
    assert action_hash("a", {"x": 1}) != action_hash("b", {"x": 1})
    assert proposal_hash(action()) == action()["payload_hash"]


def test_email_hash_is_unchanged():
    email = {"to": "a@example.test", "subject": "s", "body": "b", "in_reply_to": "e1"}
    assert proposal_hash(email) == proposal_hash({**email, "action_type": "send_email"})


def test_proposal_pauses_and_records_nothing(setup):
    view = setup.orchestrator.start("p1", RECORD_TASK)
    assert view.waiting_for_human and view.status == "awaiting_review"
    assert view.payload_hash == action_hash("record_shortlist", PAYLOAD)
    assert setup.queue.get(view.approval_id).status == "pending"
    assert setup.store.statuses_for("job-1") == {}


def test_approval_records_and_audits(setup):
    view = setup.orchestrator.start("p1", RECORD_TASK)
    final = setup.orchestrator.resume(view.thread_id, approve(view.payload_hash))
    assert final.status == "recorded" and not final.waiting_for_human
    assert setup.store.statuses_for("job-1") == {"cand-a": "shortlisted", "cand-b": "shortlisted"}
    assert setup.queue.get("p1").status == "recorded" and setup.queue.get("p1").decided_by == REVIEWER
    events = {e["event"]: e["fields"] for e in setup.audit.entries()}
    assert events["executor.outcome"]["status"] == "recorded"
    assert events["executor.outcome"]["approver"] == REVIEWER
    assert setup.audit.verify()


def test_rejection_action_records_rejected(setup):
    view = setup.orchestrator.start("p2", RECORD_TASK)
    setup.orchestrator.resume(view.thread_id, approve(view.payload_hash))
    assert setup.store.statuses_for("job-1") == {"cand-a": "rejected", "cand-b": "rejected"}


def test_human_rejection_records_nothing(setup):
    view = setup.orchestrator.start("p1", RECORD_TASK)
    final = setup.orchestrator.resume(view.thread_id, {"action": "reject", "reviewer": REVIEWER})
    assert final.status == "rejected"
    assert setup.store.statuses_for("job-1") == {}
    assert setup.orchestrator.start("p1", RECORD_TASK).status == "rejected"


def test_stale_hash_is_refused_and_review_continues(setup):
    view = setup.orchestrator.start("p1", RECORD_TASK)
    again = setup.orchestrator.resume(view.thread_id, approve("0" * 64))
    assert again.waiting_for_human and again.reason_code == "not_pending_or_text_changed"
    assert setup.store.statuses_for("job-1") == {}
    assert setup.orchestrator.resume(view.thread_id, approve(view.payload_hash)).status == "recorded"


@pytest.mark.parametrize("decision", [
    {"action": "edit", "reviewer": REVIEWER, "subject": "s", "body": "b"},
    {"action": "redraft", "reviewer": REVIEWER, "feedback": "again"},
    {"action": "approve", "reviewer": REVIEWER},
    {"action": "approve", "reviewed_hash": "x"},
])
def test_other_decisions_change_nothing(setup, decision):
    view = setup.orchestrator.start("p1", RECORD_TASK)
    again = setup.orchestrator.resume(view.thread_id, decision)
    assert again.waiting_for_human and again.message
    assert setup.queue.get("p1").status == "pending"


def test_second_resume_is_refused(setup):
    view = setup.orchestrator.start("p1", RECORD_TASK)
    setup.orchestrator.resume(view.thread_id, approve(view.payload_hash))
    with pytest.raises(ApprovalError, match="not_awaiting_review"):
        setup.orchestrator.resume(view.thread_id, approve(view.payload_hash))
    assert setup.orchestrator.start("p1", RECORD_TASK).status == "recorded"


def test_newer_proposal_supersedes_the_older_one(setup):
    old = setup.orchestrator.start("p1", RECORD_TASK)
    setup.orchestrator.start("p3", RECORD_TASK)
    assert setup.queue.get("p1").status == "superseded"
    final = setup.orchestrator.resume(old.thread_id, approve(old.payload_hash))
    assert final.status == "superseded"
    assert setup.store.statuses_for("job-1") == {}


def test_unknown_proposal_needs_a_human(setup):
    view = setup.orchestrator.start("missing", RECORD_TASK)
    assert view.status == "needs_human" and not view.waiting_for_human


def test_only_approval_leads_to_the_executor(setup):
    edges = {(edge.source, edge.target) for edge in setup.orchestrator.graph.get_graph().edges}
    assert {source for source, target in edges if target == "record_execute"} == {"record_approve"}
    assert {source for source, target in edges if target == "record_approve"} == {"record_review"}
    assert {source for source, target in edges if target == "record_propose"} == {"__start__"}


def test_executor_refuses_without_approval(setup):
    setup.queue.submit(action(), "t")
    result = execute_record("p1", queue=setup.queue, status_store=setup.store, audit=setup.audit)
    assert (result.status, result.reason) == ("refused", "status_pending")
    assert setup.store.statuses_for("job-1") == {}


def test_executor_refuses_an_action_changed_after_approval(setup):
    item = setup.queue.submit(action(), "t")
    setup.queue.approve(item.id, REVIEWER, item.payload_hash)
    tampered = '{"action_type":"record_shortlist","payload":{"job_id":"job-1","run_id":"r","candidate_ids":["cand-z"]},' \
               f'"in_reply_to":"x","payload_hash":"{item.payload_hash}","idempotency_key":"p1"}}'
    with setup.queue._connect() as db:
        db.execute("UPDATE approvals SET proposal = ? WHERE id = ?", (tampered, item.id))
    result = execute_record(item.id, queue=setup.queue, status_store=setup.store, audit=setup.audit)
    assert (result.status, result.reason) == ("refused", "text_changed_after_approval")
    assert setup.store.statuses_for("job-1") == {}


def test_executor_records_at_most_once(setup):
    item = setup.queue.submit(action(), "t")
    setup.queue.approve(item.id, REVIEWER, item.payload_hash)
    first = execute_record(item.id, queue=setup.queue, status_store=setup.store, audit=setup.audit)
    second = execute_record(item.id, queue=setup.queue, status_store=setup.store, audit=setup.audit)
    assert first.status == "recorded" and second.status == "refused"


def test_failed_write_is_marked_for_a_human(setup):
    class Broken:
        def record(self, *args):
            raise OSError("disk")

    item = setup.queue.submit(action(), "t")
    setup.queue.approve(item.id, REVIEWER, item.payload_hash)
    result = execute_record(item.id, queue=setup.queue, status_store=Broken(), audit=setup.audit)
    assert result.status == "record_failed" and setup.queue.get(item.id).status == "record_failed"


def test_email_executor_refuses_record_actions(setup):
    item = setup.queue.submit(action(), "t")
    setup.queue.approve(item.id, REVIEWER, item.payload_hash)
    result = execute_approved(item.id, queue=setup.queue, provider=None, audit=setup.audit)
    assert (result.status, result.reason) == ("refused", "unsupported_action")


def test_state_holds_ids_only(setup):
    view = setup.orchestrator.start("p1", RECORD_TASK)
    values = setup.orchestrator.graph.get_state({"configurable": {"thread_id": view.thread_id}}).values
    assert set(values) <= {"task", "email_id", "status", "approval_id", "reason_code", "message", "feedback"}
    assert values["message"] is None
