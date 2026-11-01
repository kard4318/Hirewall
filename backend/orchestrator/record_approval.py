# Human approval for actions that record a decision rather than send an email
"""A shortlist or rejection takes the same path as an email: proposed, queued,
paused for a person, and carried out only by core/executor after approval."""
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import interrupt
from pydantic import ValidationError

from core.approval_queue.approval_queue import ApprovalError, ApprovalItem, ApprovalQueue, get_approval_queue
from core.audit.audit_log import AuditLog, get_audit_sink
from core.candidate_status.store import CandidateStatusStore, get_candidate_status_store
from core.executor.executor import ExecutionResult, execute_record

from .router import APPROVED, AWAITING_REVIEW
from .state import ReviewDecision, WorkflowState

RECORD_TASK = "propose_shortlist"


@dataclass
class RecordWorkflow:
    """`build_action` turns a prepared proposal id into the action to queue. It comes from the service that owns it."""

    build_action: Callable[[str], dict[str, Any]]
    queue: ApprovalQueue = field(default_factory=get_approval_queue)
    audit: AuditLog = field(default_factory=get_audit_sink)
    status_store: CandidateStatusStore = field(default_factory=get_candidate_status_store)
    notifier: Any = None  # tells candidates about a decision after it is recorded; wired by the gateway

    def propose(self, proposal_id: str, thread_id: str) -> ApprovalItem:
        item = self.queue.submit(self.build_action(proposal_id), thread_id)
        self.audit.record("approval.submitted", approval_id=item.id, payload_hash=item.payload_hash)
        return item

    def approve(self, item_id: str, approver: str, reviewed_hash: str) -> ApprovalItem:
        item = self.queue.approve(item_id, approver, reviewed_hash)
        self.audit.record("approval.approved", approval_id=item_id, approver=approver, payload_hash=reviewed_hash)
        return item

    def reject(self, item_id: str, approver: str) -> ApprovalItem:
        item = self.queue.reject(item_id, approver)
        self.audit.record("approval.rejected", approval_id=item_id, approver=approver)
        return item

    def execute(self, item_id: str) -> ExecutionResult:
        return execute_record(
            item_id, queue=self.queue, status_store=self.status_store, audit=self.audit, notifier=self.notifier
        )


class RecordNodes:
    """Nodes can re-run after a pause or crash, so each must be safe to repeat."""

    def __init__(self, workflow: RecordWorkflow) -> None:
        self._workflow = workflow

    def propose(self, state: WorkflowState) -> dict[str, Any]:
        proposal_id = state["email_id"]  # Orchestrator.start stores the subject id under this key
        try:
            item = self._workflow.propose(proposal_id, f"{RECORD_TASK}:{proposal_id}")
        except Exception as error:
            return {"status": "needs_human", "reason_code": str(error) or "proposal_unavailable", "message": None}
        status = AWAITING_REVIEW if item.status == "pending" else item.status
        return {"status": status, "approval_id": item.id, "reason_code": None, "message": None}

    def review(self, state: WorkflowState) -> dict[str, Any]:
        """Pause for a person. Everything before interrupt() runs again on resume, so it only reads."""
        approval_id = state["approval_id"]
        item = self._workflow.queue.get(approval_id)
        answer = interrupt(
            {"approval_id": approval_id, "payload_hash": item.payload_hash, "message": state.get("message")}
        )
        try:
            decision = ReviewDecision.model_validate(answer["decision"])
        except ValidationError:
            return {"decision": None, "message": "That decision was incomplete or invalid. Nothing was changed."}
        if decision.action not in {"approve", "reject"}:
            return {"decision": None, "message": "This action can only be approved or rejected. Nothing was changed."}
        return {"decision": decision.model_dump(), "message": None}

    def approve(self, state: WorkflowState) -> dict[str, Any]:
        decision = state["decision"]
        approval_id = state["approval_id"]
        try:
            self._workflow.approve(approval_id, decision["reviewer"], decision["reviewed_hash"])
        except ApprovalError as error:
            item = self._workflow.queue.get(approval_id)
            if item.status in {"approved", "sending", "recorded"} and item.payload_hash == decision["reviewed_hash"]:
                return {"status": APPROVED}
            status = AWAITING_REVIEW if item.status == "pending" else item.status
            message = "The proposal changed after you reviewed it. Review it again." if status == AWAITING_REVIEW else None
            return {"status": status, "reason_code": str(error), "message": message}
        return {"status": APPROVED, "reason_code": None}

    def execute(self, state: WorkflowState) -> dict[str, Any]:
        approval_id = state["approval_id"]
        result = self._workflow.execute(approval_id)
        # If a crash interrupted an earlier attempt, the executor refuses to repeat it, and the queue has the truth.
        recorded = self._workflow.queue.get(approval_id).status == "recorded"
        status = "recorded" if recorded else result.status
        return {"status": status, "reason_code": None if recorded else result.reason, "message": None}

    def reject(self, state: WorkflowState) -> dict[str, Any]:
        try:
            item = self._workflow.reject(state["approval_id"], state["decision"]["reviewer"])
        except ApprovalError:
            item = self._workflow.queue.get(state["approval_id"])
        return {"status": item.status, "reason_code": None, "message": None}
