# Flags messages that require human attention

from .models import Classification, EmailType, LLMClassification, SenderKind, Urgency

_CANDIDATE_TYPES = {
    EmailType.CANDIDATE_QUESTION,
    EmailType.INTERVIEW_SCHEDULING,
    EmailType.DOCUMENT_SUBMISSION,
    EmailType.DECISION_OR_FEEDBACK,
    EmailType.COMPENSATION,
    EmailType.WITHDRAWAL,
}
_ALWAYS_HUMAN = {
    EmailType.NEW_APPLICATION,
    EmailType.COMPENSATION,
    EmailType.WITHDRAWAL,
    EmailType.EMPLOYEE_QUESTION,
    EmailType.SUSPICIOUS,
    EmailType.UNCLASSIFIED,
}
_DRAFTABLE = {EmailType.CANDIDATE_QUESTION, EmailType.INTERVIEW_SCHEDULING, EmailType.DOCUMENT_SUBMISSION}
_LOW_ONLY = {EmailType.AUTOMATIC_REPLY, EmailType.UNRELATED}
_HIGH_ALWAYS = {EmailType.WITHDRAWAL, EmailType.SUSPICIOUS}


def apply_rules(
    suggestion: LLMClassification,
    *,
    email_id: str,
    sender_kind: SenderKind,
    has_recorded_decision: bool,
    reason: str | None,
    prompt_version: str,
) -> Classification:
    """Turn the model's suggestion into a decision. The model can raise attention here, but cannot lower it."""
    rules: list[str] = []
    email_type = EmailType(suggestion.type)
    urgency: Urgency = suggestion.urgency
    needs_human = suggestion.needs_human

    # Identity comes from the sender address, so an email cannot claim to be from a candidate or an employee.
    if sender_kind != "candidate" and email_type in _CANDIDATE_TYPES:
        email_type = EmailType.UNCLASSIFIED
        rules.append("candidate_type_from_non_candidate")
    if sender_kind != "employee" and email_type == EmailType.EMPLOYEE_QUESTION:
        email_type = EmailType.UNCLASSIFIED
        rules.append("employee_type_from_non_employee")

    if email_type in _ALWAYS_HUMAN and not needs_human:
        needs_human = True
        rules.append("type_always_needs_human")
    if email_type == EmailType.DECISION_OR_FEEDBACK and not has_recorded_decision and not needs_human:
        needs_human = True
        rules.append("no_recorded_decision")
    # A real candidate's email must not disappear because it was called unrelated.
    if email_type == EmailType.UNRELATED and sender_kind != "unknown" and not needs_human:
        needs_human = True
        rules.append("known_sender_not_ignored")

    if email_type in _HIGH_ALWAYS and urgency != "high":
        urgency = "high"
        rules.append("urgency_raised_for_type")
    if email_type in _LOW_ONLY and urgency != "low":
        urgency = "low"
        rules.append("urgency_lowered_for_type")
    # A stranger cannot push an email up the queue by writing that it is urgent.
    if sender_kind == "unknown" and urgency == "high":
        urgency = "normal"
        rules.append("urgency_capped_for_unknown_sender")

    can_draft = sender_kind == "candidate" and not needs_human and email_type in _DRAFTABLE
    if email_type == EmailType.DECISION_OR_FEEDBACK:
        can_draft = sender_kind == "candidate" and has_recorded_decision and not needs_human

    return Classification(
        email_id=email_id,
        type=email_type,
        urgency=urgency,
        needs_human=needs_human,
        can_draft=can_draft,
        sender_kind=sender_kind,
        reason=reason,
        rules_applied=rules,
        prompt_version=prompt_version,
    )


def code_only_result(
    email_id: str, email_type: EmailType, sender_kind: SenderKind, reason_code: str, prompt_version: str | None = None
) -> Classification:
    """Build a result without the model. It always goes to a person."""
    urgency: Urgency = "high" if email_type in _HIGH_ALWAYS else "normal"
    return Classification(
        email_id=email_id,
        type=email_type,
        urgency=urgency,
        needs_human=True,
        can_draft=False,
        sender_kind=sender_kind,
        reason_code=reason_code,
        prompt_version=prompt_version,
    )
