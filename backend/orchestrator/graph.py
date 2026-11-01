# Agent workflow graph wiring the service nodes together

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from core.approval_queue.approval_queue import ApprovalError
from services.summarizer.classify import ClassifierDeps
from services.summarizer.node import classify_node

from .approval import DrafterWorkflow
from .checkpoints import open_checkpointer
from .router import (
    APPROVED,
    AWAITING_REVIEW,
    TASK_ROUTES,
    UNSUPPORTED_NODE,
    route_after_approve,
    route_after_classify,
    route_after_draft,
    route_after_edit,
    route_after_review,
    route_task,
)
from .state import ReviewDecision, WorkflowState

ServiceNode = Callable[[WorkflowState], dict[str, Any]]

DRAFT_TASK = "draft_reply"
TRIAGE_TASK = "triage_email"
_RECURSION_LIMIT = 100
# These outcomes stay final. Other outcomes, such as a model failure, can run again.
_FINAL_STATUSES = {"sent", "rejected", "stale", "send_failed", "refused", APPROVED, "new_application", "no_action"}


class DraftReplyNodes:
    """The steps for one reply. Nodes can re-run after a pause or crash, so each must be safe to repeat."""

    def __init__(self, workflow: DrafterWorkflow) -> None:
        self._workflow = workflow

    def draft(self, state: WorkflowState) -> dict[str, Any]:
        feedback = state.get("feedback")
        try:
            if feedback:
                proposal = self._workflow.redraft(state["approval_id"], feedback)
            else:
                proposal = self._workflow.propose(state["email_id"])
        except ApprovalError as error:
            return {"status": "needs_human", "reason_code": str(error), "message": None, "feedback": None}

        result = proposal.result
        reason = result.reason_code.value if result.reason_code else None
        if proposal.approval is None:
            # A failed redraft keeps the earlier draft in review, so the human still has something to act on.
            status = AWAITING_REVIEW if feedback else result.status
            return {"status": status, "reason_code": reason, "message": result.human_message, "feedback": None}
        item = proposal.approval
        status = AWAITING_REVIEW if item.status == "pending" else item.status
        return {
            "status": status,
            "reason_code": reason,
            "message": result.human_message,
            "approval_id": item.id,
            "feedback": None,
        }

    def human_review(self, state: WorkflowState) -> dict[str, Any]:
        """Pause for a person. Everything before interrupt() runs again on resume, so it only reads."""
        approval_id = state["approval_id"]
        item = self._workflow.queue.get(approval_id)
        answer = interrupt(
            {
                "approval_id": approval_id,
                "email_id": item.in_reply_to,
                "payload_hash": item.payload_hash,
                "message": state.get("message"),
            }
        )
        try:
            decision = ReviewDecision.model_validate(answer["decision"])
        except ValidationError:
            return {"decision": None, "message": "That decision was incomplete or invalid. Nothing was changed."}
        return {"decision": decision.model_dump(), "message": None}

    def approve(self, state: WorkflowState) -> dict[str, Any]:
        decision = state["decision"]
        approval_id = state["approval_id"]
        try:
            self._workflow.approve(approval_id, decision["reviewer"], decision["reviewed_hash"])
        except ApprovalError as error:
            item = self._workflow.queue.get(approval_id)
            already_approved = item.status in {"approved", "sending", "sent"}
            if already_approved and item.payload_hash == decision["reviewed_hash"]:
                return {"status": APPROVED}
            status = AWAITING_REVIEW if item.status == "pending" else item.status
            message = "The draft changed after you reviewed it. Review it again." if status == AWAITING_REVIEW else None
            return {"status": status, "reason_code": str(error), "message": message}
        return {"status": APPROVED, "reason_code": None}

    def send(self, state: WorkflowState) -> dict[str, Any]:
        approval_id = state["approval_id"]
        result = self._workflow.send(approval_id)
        # If a crash interrupted an earlier attempt, the executor refuses to send twice, and the queue has the truth.
        status = "sent" if self._workflow.queue.get(approval_id).status == "sent" else result.status
        return {"status": status, "reason_code": None if status == "sent" else result.reason, "message": None}

    def edit(self, state: WorkflowState) -> dict[str, Any]:
        decision = state["decision"]
        try:
            result = self._workflow.edit(
                state["approval_id"], decision["subject"], decision["body"], decision["reviewer"]
            )
        except ApprovalError as error:
            item = self._workflow.queue.get(state["approval_id"])
            status = AWAITING_REVIEW if item.status == "pending" else item.status
            return {"status": status, "reason_code": str(error), "message": "The edit could not be applied."}
        if result.proposal is None:
            return {"status": AWAITING_REVIEW, "message": result.human_message}
        warnings = ", ".join(result.proposal.warnings)
        return {"status": AWAITING_REVIEW, "message": f"The edit is saved and needs approval. Warnings: {warnings}"}

    def redraft(self, state: WorkflowState) -> dict[str, Any]:
        return {"feedback": state["decision"]["feedback"]}

    def reject(self, state: WorkflowState) -> dict[str, Any]:
        try:
            item = self._workflow.reject(state["approval_id"], state["decision"]["reviewer"])
        except ApprovalError:
            item = self._workflow.queue.get(state["approval_id"])
        return {"status": item.status, "reason_code": None, "message": None}


class TriageNodes:
    """Labels an incoming email. The label decides the next step, and nothing here sends or records."""

    def __init__(self, workflow: DrafterWorkflow, deps: ClassifierDeps) -> None:
        self._workflow = workflow
        self._deps = deps

    def classify(self, state: WorkflowState) -> dict[str, Any]:
        email = self._workflow.mailbox.get(state["email_id"])
        if email is None:
            return {"status": "needs_human", "reason_code": "email_not_found", "classification": None}
        result = classify_node({"email": email}, self._deps)["classification"]
        # Labels only. The model's reason can repeat the sender's words, so it is not saved in the workflow.
        saved = {key: result[key] for key in ("type", "urgency", "needs_human", "can_draft", "sender_kind")}
        self._workflow.audit.record(
            "classifier.outcome", email_id=state["email_id"], reason_code=result["reason_code"], **saved
        )
        return {"classification": saved, "status": _triage_status(saved), "reason_code": result["reason_code"]}


def _triage_status(classification: dict[str, Any]) -> str:
    if classification["type"] == "suspicious":
        return "quarantined"
    if classification["can_draft"]:
        return "classified"
    if classification["type"] == "new_application":
        return "new_application"
    return "needs_human" if classification["needs_human"] else "no_action"


def _unsupported_task(state: WorkflowState) -> dict[str, Any]:
    return {"status": "needs_human", "reason_code": "unsupported_task", "message": None}


def _service_node(service: ServiceNode) -> ServiceNode:
    def run(state: WorkflowState) -> dict[str, Any]:
        return {"status": "completed", **service(state)}

    return run


def build_graph(
    workflow: DrafterWorkflow,
    *,
    checkpointer: BaseCheckpointSaver,
    services: Mapping[str, ServiceNode] | None = None,
    classifier_deps: ClassifierDeps | None = None,
) -> Any:
    """Build the orchestrator. Each entry in `services` adds a task that runs that function and then ends."""
    nodes = DraftReplyNodes(workflow)
    deps = classifier_deps or ClassifierDeps(
        llm=workflow.deps.llm, candidates=workflow.deps.candidates, detector=workflow.deps.detector
    )
    builder = StateGraph(WorkflowState)

    builder.add_node("classify", TriageNodes(workflow, deps).classify)
    builder.add_conditional_edges("classify", route_after_classify, {"draft": "draft", END: END})
    builder.add_node("draft", nodes.draft)
    builder.add_node("human_review", nodes.human_review)
    builder.add_node("approve", nodes.approve)
    builder.add_node("send", nodes.send)
    builder.add_node("edit", nodes.edit)
    builder.add_node("redraft", nodes.redraft)
    builder.add_node("reject", nodes.reject)
    builder.add_node(UNSUPPORTED_NODE, _unsupported_task)

    routes = dict(TASK_ROUTES)
    for task, service in (services or {}).items():
        builder.add_node(task, _service_node(service))
        builder.add_edge(task, END)
        routes[task] = task

    builder.add_conditional_edges(
        START,
        lambda state: route_task(state, routes),
        {node: node for node in {*routes.values(), UNSUPPORTED_NODE}},
    )
    builder.add_edge(UNSUPPORTED_NODE, END)
    builder.add_conditional_edges("draft", route_after_draft, {"human_review": "human_review", END: END})
    builder.add_conditional_edges(
        "human_review",
        route_after_review,
        {name: name for name in ("human_review", "approve", "edit", "redraft", "reject")},
    )
    builder.add_conditional_edges(
        "approve", route_after_approve, {"send": "send", "human_review": "human_review", END: END}
    )
    builder.add_edge("send", END)
    builder.add_conditional_edges("edit", route_after_edit, {"human_review": "human_review", END: END})
    builder.add_edge("redraft", "draft")
    builder.add_edge("reject", END)
    return builder.compile(checkpointer=checkpointer)


@dataclass(frozen=True)
class WorkflowView:
    thread_id: str
    status: str
    waiting_for_human: bool
    approval_id: str | None = None
    payload_hash: str | None = None
    reason_code: str | None = None
    message: str | None = None
    result: dict | None = None
    classification: dict | None = None


@dataclass
class Orchestrator:
    """Starts and resumes workflows. Gateway routes should call this instead of the graph."""

    workflow: DrafterWorkflow = field(default_factory=DrafterWorkflow)
    checkpointer: BaseCheckpointSaver | None = None
    services: Mapping[str, ServiceNode] | None = None
    classifier_deps: ClassifierDeps | None = None

    def __post_init__(self) -> None:
        self.checkpointer = self.checkpointer or open_checkpointer()
        self.graph = build_graph(
            self.workflow, checkpointer=self.checkpointer, services=self.services, classifier_deps=self.classifier_deps
        )

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": _RECURSION_LIMIT}

    def view(self, thread_id: str) -> WorkflowView:
        snapshot = self.graph.get_state(self._config(thread_id))
        values = snapshot.values
        paused = [item.value for task in snapshot.tasks for item in task.interrupts]
        pause = paused[0] if paused else {}
        return WorkflowView(
            thread_id=thread_id,
            status=values.get("status", "not_started"),
            waiting_for_human=bool(paused),
            approval_id=pause.get("approval_id") or values.get("approval_id"),
            payload_hash=pause.get("payload_hash"),
            reason_code=values.get("reason_code"),
            message=pause.get("message") or values.get("message"),
            result=values.get("result"),
            classification=values.get("classification"),
        )

    def start(self, subject_id: str, task: str = DRAFT_TASK) -> WorkflowView:
        """Start a task, or return the current state if it is paused or already final. Safe to call twice."""
        thread_id = f"{task}:{subject_id}"
        current = self.view(thread_id)
        if current.waiting_for_human or current.status in _FINAL_STATUSES:
            return current
        self.graph.invoke({"task": task, "email_id": subject_id, "feedback": None}, self._config(thread_id))
        return self.view(thread_id)

    def resume(self, thread_id: str, decision: dict[str, Any]) -> WorkflowView:
        """Give a person's decision to a paused workflow. A workflow that is not paused refuses it."""
        if not self.view(thread_id).waiting_for_human:
            raise ApprovalError("not_awaiting_review")
        # Wrapped because LangGraph does not treat an empty value as a resume, and the human would get no answer.
        self.graph.invoke(Command(resume={"decision": decision}), self._config(thread_id))
        return self.view(thread_id)

    def paused_thread_for_email(self, email_id: str) -> str:
        """Find the paused workflow holding this email's draft, whichever task started it."""
        for thread_id in (f"{TRIAGE_TASK}:{email_id}", draft_thread_id(email_id)):
            if self.view(thread_id).waiting_for_human:
                return thread_id
        raise ApprovalError("not_awaiting_review")

    def diagram(self) -> str:
        return self.graph.get_graph().draw_mermaid()


def draft_thread_id(email_id: str) -> str:
    return f"{DRAFT_TASK}:{email_id}"
