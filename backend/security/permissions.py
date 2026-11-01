# Which actions with outside effects exist, who may approve them, and which executor may carry them out
"""Deny by default: an action type that is not in POLICY is refused, by the gateway and by core/executor.

Every action here has an effect outside the system (an email, a record, a calendar event), so every one needs a
human approval first. The roles are the staff roles of gateway/auth/roles.py.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ActionPolicy:
    approver_roles: frozenset[str]
    human_approval: bool
    executor: str  # the only function allowed to carry it out


_REVIEWERS = frozenset({"hr_admin", "recruiter"})

POLICY: dict[str, ActionPolicy] = {
    "send_email": ActionPolicy(_REVIEWERS, True, "core.executor.execute_approved"),
    "record_shortlist": ActionPolicy(_REVIEWERS, True, "core.executor.execute_record"),
    "record_rejection": ActionPolicy(_REVIEWERS, True, "core.executor.execute_record"),
    # Bookings run in the scheduler's calendar adapter after HR approves the slot (see docs/security.md, Known limits).
    "book_interview": ActionPolicy(_REVIEWERS, True, "scheduler.calendar_executor.book"),
    "cancel_interview": ActionPolicy(_REVIEWERS, True, "scheduler.calendar_executor.cancel"),
}


def policy_for(action_type: str | None) -> ActionPolicy | None:
    return POLICY.get(action_type or "")


def may_approve(action_type: str | None, role: str | None) -> bool:
    policy = policy_for(action_type)
    return policy is not None and role in policy.approver_roles


def execution_refusal(action_type: str | None, executor: str, approved_by: str | None) -> str | None:
    """Why this executor must not run this action, or None when it may."""
    policy = policy_for(action_type)
    if policy is None:
        return "unknown_action"
    if policy.executor != executor:
        return "wrong_executor"
    if policy.human_approval and not (approved_by or "").strip():
        return "no_human_approval"
    return None
