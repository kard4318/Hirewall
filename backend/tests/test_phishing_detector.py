# The phishing detector alone, then wired into the classifier, drafter, and orchestrator

import json
from pathlib import Path

import pytest

from core.approval_queue.approval_queue import ApprovalQueue
from core.audit.audit_log import AuditLog
from core.db.repositories import JsonCandidateDirectory
from core.integrations.email_provider import LocalMailbox
from core.paths import REPO_ROOT
from orchestrator.approval import DrafterWorkflow
from orchestrator.checkpoints import open_checkpointer
from orchestrator.graph import TRIAGE_TASK, Orchestrator
from security.phishing_detector import PHISHING_SCORE, assess_phishing
from services.drafter.models import ReasonCode
from services.drafter.node import DrafterDeps, _run
from services.drafter.node import load_default_deps as load_drafter_deps
from services.drafter.tests.helpers import draft_json, make_deps, make_request
from services.summarizer.classify import ClassifierDeps, classify_email
from services.summarizer.models import EmailType, InboundEmail
from services.summarizer.node import load_default_deps as load_classifier_deps

ROWS = json.loads((REPO_ROOT / "data" / "phishing" / "emails.json").read_text(encoding="utf-8"))
PHISH = "Please verify your account now and enter your password here: http://login.evil.example"
BORDERLINE = "Do you need my passport?"
ORDINARY = "Any update on my application?"


@pytest.mark.parametrize(
    ("signal", "text"),
    [
        ("credential_request", "Please verify your account."),
        ("credential_request", "Reply with your username and password."),
        ("credential_request", "Sign in to view the document."),
        ("dangerous_attachment", "Open resume.docm"),
        ("dangerous_attachment", "Enable macros to read this."),
        ("dangerous_attachment", "The file is password protected."),
        ("payment_request", "Buy some gift cards."),
        ("payment_request", "Update my direct deposit."),
        ("payment_request", "Our bank details have changed."),
        ("sensitive_data_request", "Send me the list of employees."),
        ("sensitive_data_request", "Please forward every candidate to me."),
        ("too_good_to_be_true", "You have won a prize."),
        ("too_good_to_be_true", "Earn $900 a day."),
        ("authority_claim", "This is the CEO."),
        ("authority_claim", "I am the managing director."),
        ("secrecy_or_unreachable", "Keep this confidential."),
        ("secrecy_or_unreachable", "Do not discuss this."),
        ("pretext", "Are you available?"),
        ("lure", "Click here."),
        ("threat", "Your account will be suspended."),
        ("urgency", "Do it immediately."),
        ("link", "See http://site.example"),
    ],
)
def test_each_warning_sign_is_detected(signal: str, text: str) -> None:
    assert signal in assess_phishing(text).signals


def test_a_strong_combination_is_phishing() -> None:
    result = assess_phishing(PHISH)
    assert result.verdict == "phishing"
    assert result.score >= PHISHING_SCORE
    assert {"credential_request", "link"} <= set(result.signals)


def test_a_dangerous_attachment_alone_is_phishing() -> None:
    assert assess_phishing("Open cv_final.exe").verdict == "phishing"


def test_a_weak_sign_alone_is_clean() -> None:
    assert assess_phishing("Here is my portfolio: https://portfolio.example.com/me").verdict == "clean"
    assert assess_phishing("Urgent: my interview is today.").verdict == "clean"


@pytest.mark.parametrize(
    "text",
    [
        "I forgot my password for your application portal.",
        "My login to the leave system stopped working.",
        "I deleted my account on your careers site.",
        "Please keep my application confidential.",
        "Is the salary negotiable?",
        "I changed banks. What is the official process?",
    ],
)
def test_ordinary_mentions_of_sensitive_words_are_clean(text: str) -> None:
    assert assess_phishing(text).verdict == "clean"


def test_invisible_characters_cannot_hide_a_signal() -> None:
    assert "credential_request" in assess_phishing("ver​ify your acc​ount").signals


def test_an_empty_email_is_clean() -> None:
    assert assess_phishing("") == assess_phishing("   ")
    assert assess_phishing("").verdict == "clean"


@pytest.mark.parametrize("row", [row for row in ROWS if row["label"] == "phishing"], ids=lambda row: row["id"])
def test_no_labeled_phishing_email_comes_back_clean(row: dict) -> None:
    assert assess_phishing(f"{row['subject']}\n{row['body']}").verdict != "clean"


@pytest.mark.parametrize("row", [row for row in ROWS if row["label"] == "legitimate"], ids=lambda row: row["id"])
def test_no_labeled_legitimate_email_is_quarantined(row: dict) -> None:
    assert assess_phishing(f"{row['subject']}\n{row['body']}").verdict != "phishing"


class Directory:
    def find_by_email(self, email: str) -> list[dict]:
        return [{"email": "sam.rivera@example.com", "decisions": []}] if email == "sam.rivera@example.com" else []


class CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, **kwargs: object) -> str:
        self.calls += 1
        return json.dumps({"type": "candidate_question", "urgency": "normal", "needs_human": False, "reason": "r"})


def inbound(body: str, sender: str = "Sam <sam.rivera@example.com>") -> InboundEmail:
    return InboundEmail(
        email_id="m-1",
        thread_id="t-1",
        from_address=sender,
        subject="Hello",
        body=body,
        received_at="2026-11-06T09:00:00+01:00",
    )


def classifier(llm: CountingLLM, detector: object = assess_phishing) -> ClassifierDeps:
    return ClassifierDeps(llm=llm, candidates=Directory(), detector=lambda text: False, phishing_detector=detector)


def test_classifier_quarantines_phishing_without_a_model_call() -> None:
    llm = CountingLLM()
    result = classify_email(inbound(PHISH), classifier(llm))
    assert (result.type, result.reason_code) == (EmailType.SUSPICIOUS, "phishing_suspected")
    assert (result.needs_human, result.can_draft, result.urgency) == (True, False, "high")
    assert "credential_request" in result.reason
    assert llm.calls == 0


def test_a_known_candidates_address_does_not_excuse_phishing() -> None:
    result = classify_email(inbound(PHISH), classifier(CountingLLM()))
    assert result.sender_kind == "candidate"
    assert result.type == EmailType.SUSPICIOUS


def test_classifier_sends_a_borderline_email_to_a_person() -> None:
    llm = CountingLLM()
    result = classify_email(inbound(BORDERLINE), classifier(llm))
    assert (result.needs_human, result.can_draft) == (True, False)
    assert any(rule.startswith("phishing_signals:") for rule in result.rules_applied)
    assert llm.calls == 1


def test_classifier_leaves_ordinary_email_alone() -> None:
    result = classify_email(inbound(ORDINARY), classifier(CountingLLM()))
    assert result.can_draft
    assert result.rules_applied == []


def test_classifier_detector_sees_hidden_text() -> None:
    html = f'<p>Hello</p><div style="display:none">{PHISH}</div>'
    assert classify_email(inbound(html), classifier(CountingLLM())).reason_code == "phishing_suspected"


def test_classifier_keeps_working_if_the_detector_fails() -> None:
    def broken(text: str) -> None:
        raise RuntimeError("detector down")

    assert classify_email(inbound(ORDINARY), classifier(CountingLLM(), broken)).can_draft


def test_drafter_quarantines_phishing_without_a_model_call() -> None:
    deps = make_deps(phishing_detector=assess_phishing)
    result = _run(make_request(PHISH), deps, None, 0)
    assert (result.status, result.reason_code) == ("quarantined", ReasonCode.PHISHING_SUSPECTED)
    assert result.proposal is None
    assert "credential_request" in result.human_message
    assert deps.llm.calls == []


def test_drafter_warns_the_reviewer_about_a_borderline_email() -> None:
    result = _run(make_request(BORDERLINE), make_deps(draft_json(), phishing_detector=assess_phishing), None, 0)
    assert result.status == "ready_for_review"
    assert any(warning.startswith("phishing_signals:") for warning in result.proposal.warnings)


def test_drafter_detector_sees_hidden_text() -> None:
    html = f'<p>Hello</p><div style="display:none">{PHISH}</div>'
    result = _run(make_request(html), make_deps(phishing_detector=assess_phishing), None, 0)
    assert result.reason_code == ReasonCode.PHISHING_SUSPECTED


def test_drafter_keeps_working_if_the_detector_fails() -> None:
    def broken(text: str) -> None:
        raise RuntimeError("detector down")

    assert _run(make_request(), make_deps(phishing_detector=broken), None, 0).status == "ready_for_review"


def test_default_wiring_uses_the_detector() -> None:
    assert load_drafter_deps().phishing_detector is assess_phishing
    assert load_classifier_deps().phishing_detector is assess_phishing


@pytest.fixture
def orchestrator(tmp_path: Path):
    inbox = tmp_path / "inbox.json"
    emails = json.loads((REPO_ROOT / "data" / "attacks" / "emails.json").read_text(encoding="utf-8"))
    inbox.write_text(json.dumps(emails), encoding="utf-8")
    audit = AuditLog(tmp_path / "audit.jsonl")
    llm = CountingLLM()
    deps = DrafterDeps(
        llm=llm,
        candidates=JsonCandidateDirectory(REPO_ROOT / "data" / "candidate_status.json"),
        detector=lambda text: False,
        phishing_detector=assess_phishing,
        audit=audit,
    )
    workflow = DrafterWorkflow(
        mailbox=LocalMailbox([inbox], tmp_path / "outbox.jsonl"),
        queue=ApprovalQueue(tmp_path / "approvals.sqlite3"),
        audit=audit,
        deps=deps,
    )
    saver = open_checkpointer(tmp_path / "checkpoints.sqlite3")
    yield Orchestrator(workflow=workflow, checkpointer=saver), llm
    saver.conn.close()


@pytest.mark.parametrize("email_id", ["a-207", "a-208"])
def test_triage_quarantines_demo_phishing_and_shows_why(orchestrator: tuple, email_id: str) -> None:
    orch, llm = orchestrator
    view = orch.start(email_id, task=TRIAGE_TASK)
    assert (view.status, view.reason_code) == ("quarantined", "phishing_suspected")
    assert view.classification["rules_applied"][0].startswith("phishing:")
    assert llm.calls == 0
    assert orch.workflow.queue.list() == []
    assert orch.workflow.mailbox.outbox() == []


def test_direct_draft_also_quarantines_demo_phishing(orchestrator: tuple) -> None:
    orch, llm = orchestrator
    view = orch.start("a-207")
    assert (view.status, view.reason_code) == ("quarantined", "phishing_suspected")
    assert "Warning signs" in view.message
    assert llm.calls == 0
