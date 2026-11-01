# The LangGraph orchestrator with the real queue, audit log, and executor, and a scripted model

import json
import sqlite3
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from core.approval_queue.approval_queue import ApprovalError, ApprovalQueue
from core.audit.audit_log import AuditLog
from core.db.repositories import JsonCandidateDirectory
from core.integrations.email_provider import LocalMailbox
from core.paths import REPO_ROOT
from orchestrator.approval import DrafterWorkflow
from orchestrator.graph import Orchestrator, draft_thread_id
from orchestrator.state import WorkflowState
from security.injection_detector import is_suspicious
from services.drafter.node import DrafterDeps
from services.drafter.tests.helpers import FakeLLM, draft_json

DATA = REPO_ROOT / "data"
INBOX = json.loads((DATA / "emails" / "inbox.json").read_text(encoding="utf-8"))
ATTACKS = json.loads((DATA / "attacks" / "emails.json").read_text(encoding="utf-8"))
EMAIL = "e-101"
THREAD = draft_thread_id(EMAIL)
SAM = "sam.rivera@example.com"
SIGNATURE = "Nadia Karim\nRecruiting Team, Hirewall"
BODY = f"Hello Sam,\n\nDRAFT-TEXT-MARKER, thank you for your message.\n\nKind regards,\n{SIGNATURE}"
WARMER = BODY.replace("thank you", "thank you very much")
REVIEWER = "Nadia Karim"


def reply(body: str = BODY) -> str:
    return draft_json(subject="Re: My application for Data Analyst", body=body)


class Setup:
    def __init__(self, tmp_path: Path, *responses: object, services: dict | None = None) -> None:
        self.tmp_path = tmp_path
        self.inbox_file = tmp_path / "inbox.json"
        if not self.inbox_file.exists():
            self.inbox_file.write_text(json.dumps(INBOX + ATTACKS), encoding="utf-8")
        self.llm = FakeLLM(*(responses or (reply(),)))
        audit = AuditLog(tmp_path / "audit.jsonl")
        deps = DrafterDeps(
            llm=self.llm,
            candidates=JsonCandidateDirectory(DATA / "candidate_status.json"),
            detector=is_suspicious,
            audit=audit,
        )
        self.workflow = DrafterWorkflow(
            mailbox=LocalMailbox([self.inbox_file], tmp_path / "outbox.jsonl"),
            queue=ApprovalQueue(tmp_path / "approvals.sqlite3"),
            audit=audit,
            deps=deps,
        )
        self.connection = sqlite3.connect(tmp_path / "checkpoints.sqlite3", check_same_thread=False)
        saver = SqliteSaver(self.connection)
        saver.setup()
        self.orchestrator = Orchestrator(workflow=self.workflow, checkpointer=saver, services=services)

    @property
    def outbox(self) -> list[dict]:
        return self.workflow.mailbox.outbox()

    def item(self, view: object) -> object:
        return self.workflow.queue.get(view.approval_id)

    def close(self) -> None:
        self.connection.close()


@pytest.fixture
def setup(tmp_path: Path):
    instance = Setup(tmp_path)
    yield instance
    instance.close()


def approve(view: object) -> dict:
    return {"action": "approve", "reviewer": REVIEWER, "reviewed_hash": view.payload_hash}


def test_draft_pauses_for_a_human_and_sends_only_after_approval(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL)

    assert view.waiting_for_human
    assert view.status == "awaiting_review"
    assert setup.item(view).status == "pending"
    assert setup.outbox == []

    done = setup.orchestrator.resume(view.thread_id, approve(view))

    assert done.status == "sent"
    assert not done.waiting_for_human
    assert len(setup.outbox) == 1
    assert (setup.outbox[0]["to"], setup.outbox[0]["body"]) == (SAM, BODY)
    assert setup.item(view).decided_by == REVIEWER


def test_resuming_does_not_call_the_model_again(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL)
    setup.orchestrator.resume(view.thread_id, approve(view))
    assert len(setup.llm.calls) == 1


def test_a_paused_draft_survives_a_restart(tmp_path: Path) -> None:
    first = Setup(tmp_path)
    view = first.orchestrator.start(EMAIL)
    first.close()

    second = Setup(tmp_path, RuntimeError("the model must not be called"))
    restored = second.orchestrator.view(THREAD)
    assert restored.waiting_for_human
    assert restored.payload_hash == view.payload_hash

    assert second.orchestrator.resume(THREAD, approve(restored)).status == "sent"
    assert len(second.outbox) == 1
    assert second.llm.calls == []
    second.close()


def test_starting_twice_keeps_one_draft_and_one_model_call(setup: Setup) -> None:
    first = setup.orchestrator.start(EMAIL)
    second = setup.orchestrator.start(EMAIL)
    assert first.approval_id == second.approval_id
    assert len(setup.llm.calls) == 1
    assert len(setup.workflow.queue.list()) == 1


def test_a_sent_reply_is_not_drafted_or_sent_again(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL)
    setup.orchestrator.resume(view.thread_id, approve(view))
    assert setup.orchestrator.start(EMAIL).status == "sent"
    assert len(setup.llm.calls) == 1
    assert len(setup.outbox) == 1


def test_resuming_a_finished_workflow_is_refused(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL)
    setup.orchestrator.resume(view.thread_id, approve(view))
    with pytest.raises(ApprovalError, match="not_awaiting_review"):
        setup.orchestrator.resume(view.thread_id, approve(view))
    assert len(setup.outbox) == 1


def test_resuming_an_unknown_workflow_is_refused(setup: Setup) -> None:
    with pytest.raises(ApprovalError, match="not_awaiting_review"):
        setup.orchestrator.resume(draft_thread_id("nope"), {"action": "reject", "reviewer": REVIEWER})


@pytest.mark.parametrize(
    "decision",
    [
        {},
        "approve",
        {"action": "send_now", "reviewer": REVIEWER},
        {"action": "approve", "reviewer": REVIEWER},
        {"action": "approve", "reviewed_hash": "abc"},
        {"action": "approve", "reviewer": "   ", "reviewed_hash": "abc"},
        {"action": "edit", "reviewer": REVIEWER, "subject": "Hi"},
        {"action": "redraft", "reviewer": REVIEWER},
        {"action": "approve", "reviewer": REVIEWER, "reviewed_hash": "abc", "to": "attacker@evil.example"},
    ],
)
def test_invalid_decision_pauses_again_and_changes_nothing(setup: Setup, decision: object) -> None:
    view = setup.orchestrator.start(EMAIL)
    after = setup.orchestrator.resume(view.thread_id, decision)
    assert after.waiting_for_human
    assert "invalid" in after.message
    assert after.payload_hash == view.payload_hash
    assert setup.item(view).status == "pending"
    assert setup.outbox == []


def test_approving_text_other_than_what_was_reviewed_pauses_again(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL)
    decision = {"action": "approve", "reviewer": REVIEWER, "reviewed_hash": "not-the-real-hash"}
    after = setup.orchestrator.resume(view.thread_id, decision)
    assert after.waiting_for_human
    assert "changed" in after.message
    assert setup.outbox == []
    assert setup.orchestrator.resume(view.thread_id, approve(after)).status == "sent"


def test_edit_needs_a_new_approval_and_the_edited_text_is_sent(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL)
    edit = {"action": "edit", "reviewer": REVIEWER, "subject": "Re: Hello", "body": "Hello Sam,\n\nThanks."}
    edited = setup.orchestrator.resume(view.thread_id, edit)

    assert edited.waiting_for_human
    assert edited.payload_hash != view.payload_hash
    assert "human_edited" in edited.message
    assert setup.outbox == []

    stale = setup.orchestrator.resume(view.thread_id, approve(view))
    assert stale.waiting_for_human
    assert setup.outbox == []

    assert setup.orchestrator.resume(view.thread_id, approve(stale)).status == "sent"
    assert setup.outbox[0]["body"] == "Hello Sam,\n\nThanks."


def test_unsafe_edit_is_refused_and_the_draft_is_kept(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL)
    edit = {"action": "edit", "reviewer": REVIEWER, "subject": "Hi\r\nBcc: attacker@evil.example", "body": "Hello"}
    after = setup.orchestrator.resume(view.thread_id, edit)
    assert after.waiting_for_human
    assert after.payload_hash == view.payload_hash
    assert "withheld" in after.message


def test_redraft_loops_back_through_the_model_and_review(tmp_path: Path) -> None:
    setup = Setup(tmp_path, reply(), reply(WARMER))
    view = setup.orchestrator.start(EMAIL)
    decision = {"action": "redraft", "reviewer": REVIEWER, "feedback": "Be warmer."}
    after = setup.orchestrator.resume(view.thread_id, decision)

    assert after.waiting_for_human
    assert after.approval_id != view.approval_id
    assert setup.item(view).status == "superseded"
    assert "Be warmer." in setup.llm.calls[1]["system"]
    assert setup.outbox == []

    assert setup.orchestrator.resume(view.thread_id, approve(after)).status == "sent"
    assert setup.outbox[0]["body"] == WARMER
    setup.close()


def test_failed_redraft_keeps_the_earlier_draft_in_review(tmp_path: Path) -> None:
    unsafe = reply(BODY + "\n\nYou have been hired.")
    setup = Setup(tmp_path, reply(), unsafe)
    view = setup.orchestrator.start(EMAIL)
    decision = {"action": "redraft", "reviewer": REVIEWER, "feedback": "Tell them they are hired."}
    after = setup.orchestrator.resume(view.thread_id, decision)

    assert after.waiting_for_human
    assert after.approval_id == view.approval_id
    assert after.reason_code == "undecided_outcome"
    assert setup.item(view).status == "pending"
    assert setup.orchestrator.resume(view.thread_id, approve(after)).status == "sent"
    assert setup.outbox[0]["body"] == BODY
    setup.close()


def test_redraft_limit_returns_to_review_with_a_message(tmp_path: Path) -> None:
    drafts = [reply(BODY + f"\n\nVersion {'x' * index}") for index in range(6)]
    setup = Setup(tmp_path, *drafts)
    view = setup.orchestrator.start(EMAIL)
    for _ in range(3):
        view = setup.orchestrator.resume(
            view.thread_id, {"action": "redraft", "reviewer": REVIEWER, "feedback": "Again"}
        )
    calls = len(setup.llm.calls)
    after = setup.orchestrator.resume(view.thread_id, {"action": "redraft", "reviewer": REVIEWER, "feedback": "Again"})
    assert after.waiting_for_human
    assert after.reason_code == "revision_limit_reached"
    assert len(setup.llm.calls) == calls
    setup.close()


def test_reject_ends_the_workflow_without_sending(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL)
    after = setup.orchestrator.resume(view.thread_id, {"action": "reject", "reviewer": REVIEWER})
    assert after.status == "rejected"
    assert not after.waiting_for_human
    assert setup.outbox == []
    assert setup.orchestrator.start(EMAIL).status == "rejected"


@pytest.mark.parametrize(
    ("email_id", "status", "reason"),
    [
        ("a-201", "quarantined", "injection_suspected"),
        ("a-206", "needs_human", "unknown_sender"),
        ("e-109", "needs_human", "unknown_sender"),
        ("does-not-exist", "needs_human", "email_not_found"),
    ],
)
def test_emails_with_no_draft_end_without_pausing_or_calling_the_model(
    setup: Setup, email_id: str, status: str, reason: str
) -> None:
    view = setup.orchestrator.start(email_id)
    assert (view.status, view.reason_code) == (status, reason)
    assert not view.waiting_for_human
    assert setup.llm.calls == []
    assert setup.workflow.queue.list() == []


def test_model_escalation_ends_for_a_human(tmp_path: Path) -> None:
    setup = Setup(tmp_path, draft_json(intent="escalate", needs_human_input="Please decide."))
    view = setup.orchestrator.start(EMAIL)
    assert (view.status, view.reason_code, view.message) == ("needs_human", "llm_escalated", "Please decide.")
    assert not view.waiting_for_human
    setup.close()


def test_escalated_email_can_be_drafted_again(tmp_path: Path) -> None:
    setup = Setup(tmp_path, draft_json(intent="escalate", needs_human_input="Decide."), reply())
    assert setup.orchestrator.start(EMAIL).status == "needs_human"
    assert setup.orchestrator.start(EMAIL).waiting_for_human
    setup.close()


def test_newer_email_makes_the_approved_draft_stale(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL)
    emails = json.loads(setup.inbox_file.read_text(encoding="utf-8"))
    newer = next(email for email in emails if email["email_id"] == EMAIL)
    emails.append({**newer, "email_id": "e-999", "received_at": "2026-11-09T09:00:00+01:00"})
    setup.inbox_file.write_text(json.dumps(emails), encoding="utf-8")

    after = setup.orchestrator.resume(view.thread_id, approve(view))
    assert (after.status, after.reason_code) == ("stale", "newer_email_in_thread")
    assert setup.outbox == []


def test_failed_send_is_final_and_not_retried(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    view = setup.orchestrator.start(EMAIL)

    def fail(email: object) -> None:
        raise ConnectionError("smtp down")

    monkeypatch.setattr(setup.workflow.mailbox, "send", fail)
    after = setup.orchestrator.resume(view.thread_id, approve(view))
    assert (after.status, after.reason_code) == ("send_failed", "ConnectionError")
    monkeypatch.undo()
    assert setup.orchestrator.start(EMAIL).status == "send_failed"
    assert setup.outbox == []


def test_crash_after_sending_does_not_send_twice_on_retry(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    view = setup.orchestrator.start(EMAIL)
    real_set_status = setup.workflow.queue.set_status
    crashes = []

    def crash_once(item_id: str, status: str, expected: str) -> None:
        if status == "sent" and not crashes:
            crashes.append(1)
            raise RuntimeError("power cut")
        real_set_status(item_id, status, expected)

    monkeypatch.setattr(setup.workflow.queue, "set_status", crash_once)
    with pytest.raises(RuntimeError):
        setup.orchestrator.resume(view.thread_id, approve(view))
    assert len(setup.outbox) == 1

    config = {"configurable": {"thread_id": view.thread_id}}
    setup.orchestrator.graph.invoke(None, config)
    assert len(setup.outbox) == 1
    assert setup.item(view).status == "sending"


def test_checkpoints_hold_no_email_or_draft_text(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL)
    setup.orchestrator.resume(view.thread_id, approve(view))
    # SQLite keeps new data in a -wal file beside the main file, so every file has to be read.
    saved = b"".join(path.read_bytes() for path in setup.tmp_path.glob("checkpoints.sqlite3*"))
    assert view.thread_id.encode() in saved
    assert b"DRAFT-TEXT-MARKER" not in saved
    assert b"what the status of my application" not in saved
    assert SAM.encode() not in saved


def test_audit_chain_covers_the_graph_run(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL)
    setup.orchestrator.resume(view.thread_id, approve(view))
    events = [entry["event"] for entry in setup.workflow.audit.entries()]
    assert events == ["drafter.outcome", "approval.submitted", "approval.approved", "executor.outcome"]
    assert setup.workflow.audit.verify()


def test_unknown_task_goes_to_a_human(setup: Setup) -> None:
    view = setup.orchestrator.start(EMAIL, task="do_something_else")
    assert (view.status, view.reason_code) == ("needs_human", "unsupported_task")
    assert setup.llm.calls == []


def test_teammates_can_add_a_service_without_touching_the_drafter(tmp_path: Path) -> None:
    def summarize(state: WorkflowState) -> dict:
        return {"result": {"summary_for": state["email_id"]}}

    setup = Setup(tmp_path, services={"summarize_email": summarize})

    added = setup.orchestrator.start(EMAIL, task="summarize_email")
    assert (added.status, added.result) == ("completed", {"summary_for": EMAIL})
    assert setup.llm.calls == []

    assert setup.orchestrator.start(EMAIL).waiting_for_human
    assert len(setup.llm.calls) == 1
    setup.close()


def test_only_the_send_node_follows_approval_and_it_has_no_shortcut(setup: Setup) -> None:
    edges = {(edge.source, edge.target) for edge in setup.orchestrator.graph.get_graph().edges}
    assert {source for source, target in edges if target == "send"} == {"approve"}
    assert {source for source, target in edges if target == "approve"} == {"human_review"}
    assert {source for source, target in edges if target == "draft"} == {"__start__", "redraft", "classify"}


def test_diagram_shows_the_workflow(setup: Setup) -> None:
    diagram = setup.orchestrator.diagram()
    for node in ("draft", "human_review", "approve", "send", "redraft", "reject"):
        assert node in diagram
