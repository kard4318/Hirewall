# Normal drafting scenarios run end to end with a scripted LLM

import json

import pytest

from services.drafter.models import ReasonCode
from services.drafter.node import draft_node

from .cases import NORMAL_CASES, Case
from .helpers import SENDER, FakeAudit, draft_json, make_deps, make_draft, make_record, make_request


@pytest.mark.parametrize("case", NORMAL_CASES, ids=lambda case: case.name)
def test_normal_case(case: Case) -> None:
    request = make_request(case.email_body, **case.request)
    deps = make_deps(json.dumps(case.draft), record=make_record(**case.record))

    result = draft_node({"draft_request": request.model_dump(mode="json")}, deps)["draft_result"]

    assert result["status"] == case.expected_status
    if case.expected_status == "ready_for_review":
        proposal = result["proposal"]
        assert proposal["intent"] == case.expected_intent
        assert proposal["to"] == SENDER
        assert proposal["body"] == case.draft["body"]
    else:
        assert result["proposal"] is None
        assert result["reason_code"] == ReasonCode.LLM_ESCALATED
        assert result["human_message"]


def test_draft_with_needs_human_input_is_escalated_even_if_intent_is_not() -> None:
    deps = make_deps(draft_json(needs_human_input="Please confirm the reply."))
    result = draft_node({"draft_request": make_request().model_dump(mode="json")}, deps)["draft_result"]
    assert result["status"] == "needs_human"
    assert result["reason_code"] == ReasonCode.LLM_ESCALATED


def test_llm_risk_flags_become_warnings() -> None:
    deps = make_deps(json.dumps(make_draft(risk_flags=["asked about other people"])))
    result = draft_node({"draft_request": make_request().model_dump(mode="json")}, deps)["draft_result"]
    assert "llm:asked about other people" in result["proposal"]["warnings"]


def test_date_echoed_from_candidate_email_warns_reviewer() -> None:
    body = "Hello Sam,\n\nThanks for your message of 3 November.\n\nKind regards,\nNadia Karim\nRecruiting Team"
    deps = make_deps(draft_json(body=body))
    request = make_request("I wrote to you on 3 November about my CV.")
    result = draft_node({"draft_request": request.model_dump(mode="json")}, deps)["draft_result"]
    assert result["status"] == "ready_for_review"
    assert "date_from_candidate_email" in result["proposal"]["warnings"]


def test_missing_detector_is_visible_to_reviewer() -> None:
    deps = make_deps(detector=None)
    result = draft_node({"draft_request": make_request().model_dump(mode="json")}, deps)["draft_result"]
    assert result["status"] == "ready_for_review"
    assert "injection_detector_unavailable" in result["proposal"]["warnings"]


def test_outcome_is_sent_to_audit_sink() -> None:
    audit = FakeAudit()
    deps = make_deps(audit=audit)
    draft_node({"draft_request": make_request().model_dump(mode="json")}, deps)
    assert audit.events[0][0] == "drafter.outcome"
    assert audit.events[0][1]["status"] == "ready_for_review"
