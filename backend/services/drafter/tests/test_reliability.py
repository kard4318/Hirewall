# Failure handling, decisions, idempotency, edits, revisions, and logging

import logging

import pytest

from services.drafter.config import DEFAULT_CONFIG
from services.drafter.context_builder import build_context
from services.drafter.models import ReasonCode
from services.drafter.node import DrafterDeps, _run, draft_node, load_default_deps, recheck_edited_draft, redraft

from .cases import ADVANCE, REJECT
from .helpers import SENDER, FakeDirectory, FakeLLM, body_saying, draft_json, make_deps, make_record, make_request


def fallback_used(result) -> bool:
    return result.status == "ready_for_review" and "fallback_template_used" in result.proposal.warnings


def context_for(record: dict | None = None):
    return build_context(make_request(), record or make_record(), SENDER, DEFAULT_CONFIG).context


def test_invalid_json_then_repaired_output_succeeds() -> None:
    llm = FakeLLM("not json", draft_json())
    result = _run(make_request(), make_deps(llm=llm), None, 0)
    assert result.status == "ready_for_review"
    assert "fallback_template_used" not in result.proposal.warnings
    assert len(llm.calls) == 2
    assert "did not match the required JSON schema" in llm.calls[1]["user"]


def test_mapping_output_is_accepted() -> None:
    llm = FakeLLM({"intent": "ack", "language": "en", "subject": "Re: Hi", "body": "Hello Sam,\n\nThanks.",
                   "claims": [], "needs_human_input": None, "risk_flags": []})  # fmt: skip
    assert _run(make_request(), make_deps(llm=llm), None, 0).status == "ready_for_review"


def test_two_invalid_outputs_use_fallback() -> None:
    llm = FakeLLM("not json", '{"intent": "ack"}')
    result = _run(make_request(), make_deps(llm=llm), None, 0)
    assert fallback_used(result)
    assert len(llm.calls) == 2
    assert "Data Analyst" in result.proposal.body
    assert result.proposal.to == SENDER


@pytest.mark.parametrize("error", [TimeoutError("timed out"), RuntimeError("provider down")])
def test_llm_exception_uses_fallback_without_retry(error: Exception) -> None:
    llm = FakeLLM(error)
    result = _run(make_request(), make_deps(llm=llm), None, 0)
    assert fallback_used(result)
    assert len(llm.calls) == 1


def test_fallback_must_pass_checks() -> None:
    record = make_record(job_title="Compensation Analyst")
    result = _run(make_request(), make_deps(RuntimeError("down"), record=record), None, 0)
    assert result.status == "needs_human"
    assert result.reason_code == ReasonCode.LLM_FAILED


def test_missing_llm_fails_safe() -> None:
    deps = DrafterDeps(llm=None, candidates=FakeDirectory(make_record()))
    result = _run(make_request(), deps, None, 0)
    assert result.reason_code == ReasonCode.LLM_UNAVAILABLE


def test_missing_directory_fails_safe() -> None:
    result = _run(make_request(), DrafterDeps(llm=FakeLLM(draft_json())), None, 0)
    assert result.reason_code == ReasonCode.CANDIDATE_LOOKUP_UNAVAILABLE


def test_failing_directory_fails_safe() -> None:
    class BrokenDirectory:
        def find_by_email(self, email: str) -> list[dict]:
            raise ConnectionError("db down")

    result = _run(make_request(), make_deps(candidates=BrokenDirectory()), None, 0)
    assert result.reason_code == ReasonCode.CANDIDATE_LOOKUP_UNAVAILABLE


def test_failing_detector_warns_reviewer() -> None:
    def broken(_text: str) -> bool:
        raise RuntimeError("detector down")

    result = _run(make_request(), make_deps(detector=broken), None, 0)
    assert "injection_detector_unavailable" in result.proposal.warnings


def test_invalid_candidate_record_fails_safe() -> None:
    record = make_record()
    del record["job_title"]
    result = _run(make_request(), make_deps(record=record), None, 0)
    assert result.reason_code == ReasonCode.INVALID_CANDIDATE_RECORD


def test_unknown_decision_type_fails_safe() -> None:
    decision = {**ADVANCE, "type": "promote"}
    result = _run(make_request(), make_deps(record=make_record(decisions=[decision])), None, 0)
    assert result.reason_code == ReasonCode.INVALID_CANDIDATE_RECORD


@pytest.mark.parametrize("state", [{}, {"draft_request": {"email": {}}}, {"draft_request": None}])
def test_invalid_request_does_not_crash_node(state: dict) -> None:
    result = draft_node(state, make_deps())["draft_result"]
    assert result["reason_code"] == ReasonCode.INVALID_REQUEST


def test_identifier_with_newline_is_rejected() -> None:
    request = make_request().model_dump(mode="json")
    request["email"]["email_id"] = "msg\nforged log line"
    result = draft_node({"draft_request": request}, make_deps())["draft_result"]
    assert result["reason_code"] == ReasonCode.INVALID_REQUEST


def test_unexpected_error_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("services.drafter.node.write_draft", explode)
    assert _run(make_request(), make_deps(), None, 0).reason_code == ReasonCode.INTERNAL_ERROR


def test_stub_dependencies_load_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.drafter.node._optional_factory", lambda module, attribute: None)
    deps = load_default_deps()
    assert deps.llm is None
    assert deps.candidates is None
    result = draft_node({"draft_request": make_request().model_dump(mode="json")})["draft_result"]
    assert result["status"] == "needs_human"
    assert result["reason_code"] == ReasonCode.CANDIDATE_LOOKUP_UNAVAILABLE


def test_failing_factory_does_not_crash_node(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_factory() -> None:
        raise RuntimeError("missing API key")

    monkeypatch.setattr("services.drafter.node._optional_factory", lambda module, attribute: broken_factory)
    result = draft_node({"draft_request": make_request().model_dump(mode="json")})["draft_result"]
    assert result["status"] == "needs_human"


def test_implemented_factories_are_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = FakeLLM(draft_json())
    factories = {"get_llm_client": lambda: llm, "get_candidate_directory": lambda: FakeDirectory(make_record())}
    monkeypatch.setattr("services.drafter.node._optional_factory", lambda module, attribute: factories.get(attribute))
    result = draft_node({"draft_request": make_request().model_dump(mode="json")})["draft_result"]
    assert result["status"] == "ready_for_review"
    assert len(llm.calls) == 1


@pytest.mark.parametrize(
    "sentence",
    ["We will not be moving forward with your application.", "We won't be moving forward with your application."],
)
def test_rejection_wording_needs_a_recorded_rejection_not_an_advance(sentence: str) -> None:
    advance_only = make_record(decisions=[ADVANCE])
    blocked = _run(make_request(), make_deps(draft_json(body=body_saying(sentence)), record=advance_only), None, 0)
    assert blocked.status == "needs_human"
    rejected = make_record(decisions=[REJECT])
    allowed = _run(make_request(), make_deps(draft_json(body=body_saying(sentence)), record=rejected), None, 0)
    assert allowed.status == "ready_for_review"


def test_advance_wording_needs_a_recorded_advance() -> None:
    sentence = "We are moving forward with your application."
    blocked = _run(make_request(), make_deps(draft_json(body=body_saying(sentence))), None, 0)
    assert blocked.reason_code == ReasonCode.UNDECIDED_OUTCOME
    record = make_record(decisions=[ADVANCE])
    allowed = _run(make_request(), make_deps(draft_json(body=body_saying(sentence)), record=record), None, 0)
    assert allowed.status == "ready_for_review"


def test_recorded_rejection_allows_only_that_decision() -> None:
    record = make_record(decisions=[REJECT])
    allowed = _run(
        make_request(),
        make_deps(draft_json(body=body_saying("We will not be moving forward.")), record=record),
        None,
        0,
    )
    assert allowed.status == "ready_for_review"

    for sentence in ("You have been hired.", "Your salary will be competitive.", "You are in the next round."):
        blocked = _run(make_request(), make_deps(draft_json(body=body_saying(sentence)), record=record), None, 0)
        assert blocked.status == "needs_human"
        assert ReasonCode.UNDECIDED_OUTCOME.value in blocked.human_message


def test_rerun_keeps_idempotency_key_and_hash() -> None:
    first = _run(make_request(), make_deps(), None, 0).proposal
    second = _run(make_request(), make_deps(), None, 0).proposal
    assert first.idempotency_key == second.idempotency_key
    assert first.payload_hash == second.payload_hash


def test_text_change_changes_hash_but_not_key() -> None:
    first = _run(make_request(), make_deps(), None, 0).proposal
    other = draft_json(body=body_saying("Thank you for your message."))
    second = _run(make_request(), make_deps(other), None, 0).proposal
    assert first.idempotency_key == second.idempotency_key
    assert first.payload_hash != second.payload_hash


def test_node_output_is_json_compatible_and_has_no_send_side_effect() -> None:
    llm = FakeLLM(draft_json())
    output = draft_node({"draft_request": make_request().model_dump(mode="json")}, make_deps(llm=llm))
    assert set(output) == {"draft_result"}
    assert output["draft_result"]["proposal"]["action_type"] == "send_email"
    assert len(llm.calls) == 1


def test_recruiter_edit_gets_new_hash_and_warnings() -> None:
    proposal = _run(make_request(), make_deps(), None, 0).proposal
    result = recheck_edited_draft(
        proposal, "Re: My application", "Hello Sam,\r\n\r\nWe offer $90,000. You have been hired.", context_for()
    )
    edited = result.proposal
    assert result.status == "ready_for_review"
    assert edited.payload_hash != proposal.payload_hash
    assert edited.idempotency_key == proposal.idempotency_key
    assert edited.to == proposal.to
    assert "\r" not in edited.body
    for warning in ("human_edited", "claims_not_reverified", "edit_warning:unsupported_amount",
                    "edit_warning:undecided_outcome"):  # fmt: skip
        assert warning in edited.warnings


def test_clean_edit_has_no_content_warnings() -> None:
    proposal = _run(make_request(), make_deps(), None, 0).proposal
    edited = recheck_edited_draft(proposal, "Re: Hello", "Hello Sam,\n\nThanks!", context_for()).proposal
    assert edited.warnings == ["human_edited", "claims_not_reverified"]


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("Re: Hi\r\nBcc: attacker@evil.example", "Hello"),
        ("Re: Hi", "<script>alert(1)</script>"),
        ("Re: Hi", "   "),
        ("", "Hello"),
    ],
)
def test_format_failure_in_edit_stays_blocking(subject: str, body: str) -> None:
    proposal = _run(make_request(), make_deps(), None, 0).proposal
    result = recheck_edited_draft(proposal, subject, body, context_for())
    assert result.status == "needs_human"
    assert result.proposal is None
    assert result.reason_code == ReasonCode.FORMAT_INVALID


def test_redraft_passes_feedback_as_trusted_and_does_not_keep_it() -> None:
    llm = FakeLLM(draft_json(body=body_saying("We can meet on 20 November 2026.")), draft_json())
    deps = make_deps(llm=llm)
    result = redraft(make_request(), "Offer 20 November 2026 instead.", 1, deps)
    assert result.status == "ready_for_review"
    assert result.proposal.revision == 1
    assert "Offer 20 November 2026 instead." in llm.calls[0]["system"]
    assert "Offer 20 November 2026 instead." not in llm.calls[0]["user"]

    _run(make_request(), deps, None, 0)
    assert "Offer 20 November 2026 instead." not in llm.calls[1]["system"]


def test_redraft_changes_idempotency_key() -> None:
    original = _run(make_request(), make_deps(), None, 0).proposal
    revised = redraft(make_request(), "Be warmer.", 1, make_deps()).proposal
    assert revised.idempotency_key != original.idempotency_key


def test_feedback_does_not_count_as_a_recorded_decision() -> None:
    deps = make_deps(draft_json(body=body_saying("You have been hired.")))
    result = redraft(make_request(), "Tell the candidate they have been hired.", 1, deps)
    assert result.status == "needs_human"
    assert ReasonCode.UNDECIDED_OUTCOME.value in result.human_message


def test_redraft_failure_does_not_use_fallback() -> None:
    result = redraft(make_request(), "Be warmer.", 1, make_deps(RuntimeError("down")))
    assert result.status == "needs_human"
    assert result.reason_code == ReasonCode.LLM_FAILED


def test_revision_limit_is_enforced() -> None:
    llm = FakeLLM(draft_json())
    assert redraft(make_request(), "Again.", DEFAULT_CONFIG.max_revisions, make_deps(llm=llm)).proposal is not None
    calls = len(llm.calls)
    result = redraft(make_request(), "Again.", DEFAULT_CONFIG.max_revisions + 1, make_deps(llm=llm))
    assert result.reason_code == ReasonCode.REVISION_LIMIT_REACHED
    assert len(llm.calls) == calls


@pytest.mark.parametrize(
    "response",
    [
        draft_json(body=body_saying("Thanks for DRAFT-TEXT-MARKER.")),
        draft_json(body=body_saying("DRAFT-TEXT-MARKER: you have been hired.")),
        "invalid DRAFT-TEXT-MARKER",
        RuntimeError("provider echoed EMAIL-BODY-MARKER and DRAFT-TEXT-MARKER"),
    ],
)
def test_no_email_or_draft_text_in_logs(caplog: pytest.LogCaptureFixture, response: object) -> None:
    caplog.set_level(logging.DEBUG)
    result = _run(make_request("EMAIL-BODY-MARKER"), make_deps(response), None, 0)
    assert result is not None
    assert caplog.records
    assert "EMAIL-BODY-MARKER" not in caplog.text
    assert "DRAFT-TEXT-MARKER" not in caplog.text
    assert SENDER not in caplog.text


def test_internal_error_log_has_type_only(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("EMAIL-BODY-MARKER")

    monkeypatch.setattr("services.drafter.node.write_draft", explode)
    caplog.set_level(logging.DEBUG)
    _run(make_request("EMAIL-BODY-MARKER"), make_deps(), None, 0)
    assert "RuntimeError" in caplog.text
    assert "EMAIL-BODY-MARKER" not in caplog.text
