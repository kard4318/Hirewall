# Routing logic choosing the next node in the workflow

from collections.abc import Mapping

from langgraph.graph import END

from .state import WorkflowState

# Each task maps to the node that starts it. Routing is done by code, so an email's text cannot choose a route.
TASK_ROUTES: dict[str, str] = {"draft_reply": "draft", "triage_email": "classify", "daily_digest": "digest"}
UNSUPPORTED_NODE = "unsupported_task"
AWAITING_REVIEW = "awaiting_review"
APPROVED = "approved"


def route_task(state: WorkflowState, routes: Mapping[str, str]) -> str:
    return routes.get(state.get("task", ""), UNSUPPORTED_NODE)


def route_after_classify(state: WorkflowState) -> str:
    """A label can only lead to the drafter, which runs its own checks and pauses for a person."""
    classification = state.get("classification") or {}
    return "draft" if classification.get("can_draft") else END


def route_after_draft(state: WorkflowState) -> str:
    return "human_review" if state.get("status") == AWAITING_REVIEW else END


def route_after_review(state: WorkflowState) -> str:
    decision = state.get("decision")
    return decision["action"] if decision else "human_review"


def route_after_approve(state: WorkflowState) -> str:
    status = state.get("status")
    if status == APPROVED:
        return "send"
    return "human_review" if status == AWAITING_REVIEW else END


def route_after_edit(state: WorkflowState) -> str:
    return "human_review" if state.get("status") == AWAITING_REVIEW else END
