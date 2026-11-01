# Regressions for problems found by running the drafter against a real local model

import pytest

from services.drafter.checks import extract_values
from services.drafter.config import DEFAULT_CONFIG
from services.drafter.context_builder import build_context
from services.drafter.models import ReasonCode
from services.drafter.node import _run
from services.drafter.writer import build_messages

from .cases import INTERVIEW, REJECT, SLOTS
from .helpers import SENDER, body_saying, draft_json, make_deps, make_record, make_request


def scheduling_draft(claim_text: str, source_field: str, sentence: str) -> str:
    return draft_json(
        intent="scheduling",
        body=body_saying(sentence),
        claims=[{"text": claim_text, "source_field": source_field}],
    )


@pytest.mark.parametrize(
    "text",
    ["2026-11-12T10:00:00+00:00", "2026-11-12 10:00:00+00:00", "2026-11-12T10:00:00Z", "2026-11-12T10:00+0100"],
)
def test_timezone_offset_is_not_read_as_a_time(text: str) -> None:
    values = extract_values(text)
    assert values.time_groups == [(600,)]
    assert values.numbers == set()


def test_iso_date_without_time_has_no_time() -> None:
    values = extract_values("2026-11-12")
    assert values.time_groups == []
    assert len(values.date_groups) == 1


@pytest.mark.parametrize(
    "claim_text",
    ["2026-11-12 10:00:00+00:00", "2026-11-12T10:00:00+00:00", "12 November 2026 at 10:00", "12 November 2026"],
)
def test_interview_claim_in_any_date_format_is_supported(claim_text: str) -> None:
    draft = scheduling_draft(claim_text, "interview.scheduled_at", "Your interview is on 12 November 2026 at 10:00.")
    result = _run(make_request(), make_deps(draft, record=make_record(interview=INTERVIEW)), None, 0)
    assert result.status == "ready_for_review"


@pytest.mark.parametrize("claim_text", ["2026-11-12 11:00:00+00:00", "13 November 2026", "12 November 2026 at 11:00"])
def test_claim_with_the_wrong_date_or_time_stays_blocked(claim_text: str) -> None:
    draft = scheduling_draft(claim_text, "interview.scheduled_at", "Your interview is on 12 November 2026 at 10:00.")
    result = _run(make_request(), make_deps(draft, record=make_record(interview=INTERVIEW)), None, 0)
    assert result.status == "needs_human"
    assert ReasonCode.CLAIM_UNSUPPORTED.value in result.human_message


def test_invented_field_path_stays_blocked() -> None:
    draft = scheduling_draft("13 November 2026 at 14:00", "interview.proposed_slots.0", "We noted 13 November 2026.")
    result = _run(make_request(approved_slots=SLOTS), make_deps(draft), None, 0)
    assert result.status == "needs_human"
    assert ReasonCode.CLAIM_UNSUPPORTED.value in result.human_message


def system_prompt(**record: object) -> str:
    context = build_context(make_request(approved_slots=SLOTS), make_record(**record), SENDER, DEFAULT_CONFIG).context
    return build_messages(context, DEFAULT_CONFIG, "UNTRUSTED_FIXED")[0]


def test_prompt_lists_exact_paths_and_readable_dates() -> None:
    system = system_prompt(interview=INTERVIEW)
    assert "interview.scheduled_at: 12 November 2026 at 10:00" in system
    assert "interview.location: Meeting Room 4" in system
    assert "proposed_slots.0: 13 November 2026 at 14:00" in system
    assert "proposed_slots.1: 16 November 2026 at 09:30" in system
    assert "documents_missing.0: Portfolio" in system
    assert "+00:00" not in system


def test_prompt_shows_empty_fields_as_none() -> None:
    system = system_prompt()
    assert "interview: (none)" in system
    assert "decisions: (none)" in system


def test_prompt_keeps_multi_line_signature_on_one_line() -> None:
    assert 'recruiter_signature: "Nadia Karim\\nRecruiting Team"' in system_prompt()


def test_every_listed_path_can_be_cited() -> None:
    """A model that copies paths from the prompt must get paths the claim check accepts."""
    from services.drafter.checks import _resolve_path

    context = build_context(
        make_request(approved_slots=SLOTS), make_record(interview=INTERVIEW), SENDER, DEFAULT_CONFIG
    ).context
    start, end = "# Trusted context\n\n", "\n"
    section = build_messages(context, DEFAULT_CONFIG, "UNTRUSTED_FIXED")[0].split(start)[1]
    paths = [line.split(": ", 1)[0] for line in section.strip().split(end)]
    assert "interview.scheduled_at" in paths
    for path in paths:
        assert _resolve_path(context.trusted_view(), path)[0], path


@pytest.mark.parametrize(
    "sentence",
    [
        "We will send a calendar invitation.",
        "We will be in touch shortly.",
        "We’ll follow up with you.",
        "Expect news soon.",
    ],
)
def test_unconfirmed_promise_warns_the_reviewer(sentence: str) -> None:
    result = _run(make_request(), make_deps(draft_json(body=body_saying(sentence))), None, 0)
    assert result.status == "ready_for_review"
    assert "promise_to_confirm" in result.proposal.warnings


def test_plain_reply_has_no_promise_warning() -> None:
    result = _run(make_request(), make_deps(draft_json(body=body_saying("Thank you for your message."))), None, 0)
    assert "promise_to_confirm" not in result.proposal.warnings


OMAR_WRONG_BODY = "No, your CV is all we need at this stage."


def test_unused_claim_on_an_acknowledgement_warns_the_reviewer() -> None:
    """The real model often cites a true fact that its short acknowledgement does not use."""
    draft = draft_json(
        body=body_saying("Thank you for your message."),
        claims=[{"text": "Portfolio", "source_field": "documents_missing.0"}],
    )
    result = _run(make_request(), make_deps(draft), None, 0)
    assert result.status == "ready_for_review"
    assert "claim_not_in_draft" in result.proposal.warnings


def test_factual_reply_whose_only_claim_is_unused_is_blocked() -> None:
    """The real model cited documents_missing.0 while writing a reply that never mentioned that document."""
    draft = draft_json(
        intent="status_update",
        body=body_saying("Thank you for your CV."),
        claims=[{"text": "Portfolio", "source_field": "documents_missing.0"}],
    )
    result = _run(make_request(), make_deps(draft), None, 0)
    assert result.status == "needs_human"
    assert ReasonCode.CLAIM_UNSUPPORTED.value in result.human_message


@pytest.mark.parametrize(
    "sentence",
    [
        OMAR_WRONG_BODY,
        "We have everything we need.",
        "We need nothing else from you.",
        "No further documents are required.",
    ],
)
def test_saying_nothing_is_needed_while_documents_are_missing_is_blocked(sentence: str) -> None:
    result = _run(make_request(), make_deps(draft_json(body=body_saying(sentence))), None, 0)
    assert result.status == "needs_human"
    assert ReasonCode.CONTRADICTS_RECORD.value in result.human_message


def test_saying_nothing_is_needed_is_allowed_when_nothing_is_missing() -> None:
    record = make_record(documents_missing=[])
    result = _run(make_request(), make_deps(draft_json(body=body_saying(OMAR_WRONG_BODY)), record=record), None, 0)
    assert result.status == "ready_for_review"


def test_slot_claim_passes_when_body_lists_several_dates() -> None:
    draft = draft_json(
        intent="scheduling",
        body=body_saying("We can meet on 13 November 2026 at 14:00 or 16 November 2026 at 09:30."),
        claims=[{"text": "16 November 2026 at 09:30", "source_field": "proposed_slots.1"}],
    )
    assert _run(make_request(approved_slots=SLOTS), make_deps(draft), None, 0).status == "ready_for_review"


DECIDED_NOT_TO_MOVE = "We have decided not to move forward with your application."


def test_decided_not_to_move_forward_needs_a_recorded_rejection() -> None:
    unrecorded = _run(make_request(), make_deps(draft_json(body=body_saying(DECIDED_NOT_TO_MOVE))), None, 0)
    assert unrecorded.status == "needs_human"
    assert ReasonCode.UNDECIDED_OUTCOME.value in unrecorded.human_message


def test_decided_not_to_move_forward_passes_with_a_recorded_rejection() -> None:
    draft = draft_json(
        intent="status_update",
        body=body_saying(DECIDED_NOT_TO_MOVE),
        claims=[{"text": "not moving forward", "source_field": "decisions.0.details"}],
    )
    result = _run(make_request(), make_deps(draft, record=make_record(decisions=[REJECT])), None, 0)
    assert result.status == "ready_for_review"


def test_decision_author_and_date_are_not_shown_to_the_model() -> None:
    system = system_prompt(decisions=[REJECT])
    assert "decisions.0.type: reject" in system
    assert "decisions.0.details: not moving forward" in system
    assert "decided_by" not in system
    assert "decided_at" not in system
    assert "1 November 2026" not in system


@pytest.mark.parametrize(
    "sentence",
    [
        "Yes, your Portfolio arrived perfectly fine.",
        "We have received your CV and Portfolio.",
        "We got your portfolio, thanks!",
        "We do not require any additional documents at this time.",
        "We don't need anything more from you.",
        "Your CV and cover letter are sufficient to review your application.",
    ],
)
def test_draft_saying_a_missing_document_is_not_needed_or_arrived_is_blocked(sentence: str) -> None:
    result = _run(make_request(), make_deps(draft_json(body=body_saying(sentence))), None, 0)
    assert result.status == "needs_human"
    assert ReasonCode.CONTRADICTS_RECORD.value in result.human_message


@pytest.mark.parametrize(
    "sentence",
    [
        "We have received your CV, but we are still missing your Portfolio.",
        "We have not received your Portfolio yet.",
        "Please send your Portfolio.",
        "Your Portfolio hasn't arrived.",
        "We have received your CV.",
    ],
)
def test_draft_correctly_describing_missing_documents_passes(sentence: str) -> None:
    result = _run(make_request(), make_deps(draft_json(body=body_saying(sentence))), None, 0)
    assert result.status == "ready_for_review"


def test_received_document_can_be_confirmed_when_nothing_is_missing() -> None:
    record = make_record(documents_missing=[], documents_received=["CV", "Portfolio"])
    draft = draft_json(body=body_saying("Yes, your Portfolio arrived."))
    assert _run(make_request(), make_deps(draft, record=record), None, 0).status == "ready_for_review"


def test_relative_date_echoed_from_the_candidate_warns_instead_of_blocking() -> None:
    """The real model replied with the subject "Re: Interview next week", and that was blocked as invented."""
    request = make_request(email={"subject": "Interview next week"})
    draft = draft_json(subject="Re: Interview next week")
    result = _run(request, make_deps(draft), None, 0)
    assert result.status == "ready_for_review"
    assert "date_from_candidate_email" in result.proposal.warnings


def test_relative_date_the_candidate_never_wrote_stays_blocked() -> None:
    draft = draft_json(body=body_saying("We will reply next week."))
    result = _run(make_request(), make_deps(draft), None, 0)
    assert result.reason_code == ReasonCode.UNSUPPORTED_DATE


def test_draft_mentioning_the_trusted_context_is_blocked() -> None:
    draft = draft_json(body=body_saying("The trusted context shows nothing new."))
    assert ReasonCode.INTERNAL_DATA.value in _run(make_request(), make_deps(draft), None, 0).human_message


@pytest.mark.parametrize("stage", ["closed", "screening_complete", "interview_scheduled"])
def test_saying_under_review_at_another_stage_is_blocked_whatever_it_cites(stage: str) -> None:
    """The real model told rejected and advanced candidates their application was under review."""
    draft = draft_json(body=body_saying("Your application is currently under review."))
    result = _run(make_request(), make_deps(draft, record=make_record(stage=stage)), None, 0)
    assert result.status == "needs_human"
    assert ReasonCode.CONTRADICTS_RECORD.value in result.human_message


def test_saying_under_review_at_that_stage_passes() -> None:
    draft = draft_json(body=body_saying("Your application is currently under review."))
    assert _run(make_request(), make_deps(draft), None, 0).status == "ready_for_review"


@pytest.mark.parametrize(
    "sentence",
    [
        "Your background looks strong.",
        "It sounds like a solid experience.",
        "You seem like a good fit.",
        "You are a strong candidate.",
        "We haven't made a final decision yet.",
        "We have not made a decision.",
        "No decision has been made.",
    ],
)
def test_invented_feedback_or_decision_status_is_blocked_without_a_recorded_decision(sentence: str) -> None:
    result = _run(make_request(), make_deps(draft_json(body=body_saying(sentence))), None, 0)
    assert result.status == "needs_human"
    assert ReasonCode.UNDECIDED_OUTCOME.value in result.human_message


def test_prompt_does_not_suggest_a_stage_value() -> None:
    """An example such as "under review" made the model copy it for every candidate."""
    system = system_prompt(stage="closed")
    assert "under review" not in system
    assert "under_review" not in system


def test_raw_field_value_warns_the_reviewer() -> None:
    draft = draft_json(body=body_saying("You are at the screening_complete stage."))
    result = _run(make_request(), make_deps(draft), None, 0)
    assert "raw_field_value" in result.proposal.warnings
