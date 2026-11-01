# The triage task: the classifier labels an email, and the label chooses the next step

import json
from pathlib import Path

import pytest

from core.approval_queue.approval_queue import ApprovalError
from orchestrator.graph import TRIAGE_TASK
from services.drafter.tests.helpers import draft_json

from .test_orchestrator import BODY, EMAIL, REVIEWER, Setup, approve, reply

THREAD = f"{TRIAGE_TASK}:{EMAIL}"


def label(email_type: str = "candidate_question", urgency: str = "normal", human: bool = False) -> str:
    return json.dumps({"type": email_type, "urgency": urgency, "needs_human": human, "reason": "SHORT-REASON-MARKER"})


def start(setup: Setup, email_id: str = EMAIL) -> object:
    return setup.orchestrator.start(email_id, task=TRIAGE_TASK)


def test_routine_email_is_classified_drafted_and_paused_for_a_person(tmp_path: Path) -> None:
    setup = Setup(tmp_path, label(), reply())
    view = start(setup)

    assert view.waiting_for_human
    assert view.classification["type"] == "candidate_question"
    assert len(setup.llm.calls) == 2
    assert setup.outbox == []

    assert setup.orchestrator.resume(view.thread_id, approve(view)).status == "sent"
    assert setup.outbox[0]["body"] == BODY
    assert len(setup.llm.calls) == 2
    setup.close()


@pytest.mark.parametrize(
    ("email_type", "human", "status"),
    [
        ("compensation", False, "needs_human"),
        ("withdrawal", False, "needs_human"),
        ("candidate_question", True, "needs_human"),
    ],
)
def test_label_that_needs_a_person_never_reaches_the_drafter(
    tmp_path: Path, email_type: str, human: bool, status: str
) -> None:
    setup = Setup(tmp_path, label(email_type, human=human), RuntimeError("the drafter must not run"))
    view = start(setup)
    assert view.status == status
    assert not view.waiting_for_human
    assert len(setup.llm.calls) == 1
    assert setup.workflow.queue.list() == []
    setup.close()


def test_new_applicant_stops_with_a_label_and_nothing_is_recorded(tmp_path: Path) -> None:
    setup = Setup(tmp_path, label("new_application"))
    candidates_before = setup.workflow.deps.candidates.find_by_email("morgan.blake@example.com")
    view = start(setup, "e-109")

    assert view.status == "new_application"
    assert view.classification["sender_kind"] == "unknown"
    assert not view.waiting_for_human
    assert setup.workflow.queue.list() == []
    assert setup.outbox == []
    assert setup.workflow.deps.candidates.find_by_email("morgan.blake@example.com") == candidates_before == []
    setup.close()


def test_stranger_labeled_as_a_candidate_goes_to_a_person_without_a_draft(tmp_path: Path) -> None:
    setup = Setup(tmp_path, label("candidate_question"), RuntimeError("the drafter must not run"))
    view = start(setup, "e-109")
    assert view.status == "needs_human"
    assert view.classification["type"] == "unclassified"
    assert len(setup.llm.calls) == 1
    setup.close()


def test_noise_ends_with_no_action(tmp_path: Path) -> None:
    setup = Setup(tmp_path, label("unrelated", "low"))
    view = start(setup, "e-109")
    assert view.status == "no_action"
    assert not view.classification["needs_human"]
    assert start(setup, "e-109").status == "no_action"
    assert len(setup.llm.calls) == 1
    setup.close()


def test_attack_is_quarantined_without_calling_the_model(tmp_path: Path) -> None:
    setup = Setup(tmp_path, RuntimeError("the model must not run"))
    view = start(setup, "a-201")
    assert view.status == "quarantined"
    assert view.classification["type"] == "suspicious"
    assert setup.llm.calls == []
    setup.close()


def test_classifier_failure_goes_to_a_person(tmp_path: Path) -> None:
    setup = Setup(tmp_path, RuntimeError("model down"))
    view = start(setup)
    assert (view.status, view.reason_code) == ("needs_human", "llm_failed")
    assert not view.waiting_for_human
    setup.close()


def test_failed_triage_can_run_again(tmp_path: Path) -> None:
    setup = Setup(tmp_path, RuntimeError("model down"), label(), reply())
    assert start(setup).status == "needs_human"
    assert start(setup).waiting_for_human
    setup.close()


def test_unknown_email_goes_to_a_person(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    view = start(setup, "does-not-exist")
    assert (view.status, view.reason_code) == ("needs_human", "email_not_found")
    assert setup.llm.calls == []
    setup.close()


def test_drafter_can_still_refuse_after_the_classifier_allowed_it(tmp_path: Path) -> None:
    setup = Setup(tmp_path, label(), draft_json(intent="escalate", needs_human_input="Decide."))
    view = start(setup)
    assert (view.status, view.reason_code) == ("needs_human", "llm_escalated")
    setup.close()


def test_triage_and_direct_draft_tasks_are_separate(tmp_path: Path) -> None:
    setup = Setup(tmp_path, reply())
    direct = setup.orchestrator.start(EMAIL)
    assert direct.waiting_for_human
    assert direct.classification is None
    assert setup.orchestrator.paused_thread_for_email(EMAIL) == direct.thread_id
    setup.close()


def test_paused_thread_lookup_finds_a_triage_draft_and_refuses_otherwise(tmp_path: Path) -> None:
    setup = Setup(tmp_path, label(), reply())
    view = start(setup)
    assert setup.orchestrator.paused_thread_for_email(EMAIL) == view.thread_id
    setup.orchestrator.resume(view.thread_id, {"action": "reject", "reviewer": REVIEWER})
    with pytest.raises(ApprovalError):
        setup.orchestrator.paused_thread_for_email(EMAIL)
    setup.close()


def test_only_the_classifier_and_existing_paths_lead_to_the_drafter(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    edges = {(edge.source, edge.target) for edge in setup.orchestrator.graph.get_graph().edges}
    assert {target for source, target in edges if source == "classify"} == {"draft", "__end__"}
    assert {source for source, target in edges if target == "send"} == {"approve"}
    setup.close()


def test_audit_records_the_label_without_email_text(tmp_path: Path) -> None:
    setup = Setup(tmp_path, label("compensation"))
    start(setup)
    entry = next(item for item in setup.workflow.audit.entries() if item["event"] == "classifier.outcome")
    assert entry["fields"]["type"] == "compensation"
    assert "what the status" not in json.dumps(setup.workflow.audit.entries())
    assert "SHORT-REASON-MARKER" not in json.dumps(setup.workflow.audit.entries())
    setup.close()


def test_checkpoints_hold_labels_but_no_email_text_or_model_reason(tmp_path: Path) -> None:
    setup = Setup(tmp_path, label("compensation"))
    start(setup)
    saved = b"".join(path.read_bytes() for path in tmp_path.glob("checkpoints.sqlite3*"))
    assert b"compensation" in saved
    assert b"SHORT-REASON-MARKER" not in saved
    assert b"what the status" not in saved
    setup.close()
