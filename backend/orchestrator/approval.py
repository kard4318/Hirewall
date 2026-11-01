# Pauses the workflow and hands proposed actions to the approval queue

import os
from dataclasses import dataclass, field
from typing import Any

from core.approval_queue.approval_queue import ApprovalError, ApprovalItem, ApprovalQueue, get_approval_queue
from core.audit.audit_log import AuditLog, get_audit_sink
from core.executor.executor import ExecutionResult, execute_approved
from core.integrations.email_provider import LocalMailbox, get_mailbox
from services.drafter.models import DraftRequest, DraftResult, ProposedAction
from services.drafter.node import (
    DrafterDeps,
    build_review_context,
    draft_node,
    load_default_deps,
    recheck_edited_draft,
    redraft,
)

_DEFAULT_SIGNATURE = "Nadia Karim\nRecruiting Team, Hirewall"


@dataclass(frozen=True)
class Proposal:
    result: DraftResult
    approval: ApprovalItem | None = None


@dataclass
class DrafterWorkflow:
    """Connects the drafter, the approval queue, and the executor. Only a human approval leads to a send."""

    mailbox: LocalMailbox = field(default_factory=get_mailbox)
    queue: ApprovalQueue = field(default_factory=get_approval_queue)
    audit: AuditLog = field(default_factory=get_audit_sink)
    deps: DrafterDeps = field(default_factory=load_default_deps)

    def _request(self, email_id: str, approved_slots: list[str] | None = None) -> tuple[DraftRequest, dict[str, Any]]:
        email = self.mailbox.get(email_id)
        if email is None:
            raise ApprovalError("email_not_found")
        request = DraftRequest.model_validate(
            {
                "email": email,
                "thread_history": self.mailbox.thread_history(email),
                "recruiter_signature": os.getenv("RECRUITER_SIGNATURE") or _DEFAULT_SIGNATURE,
                "approved_slots": approved_slots or [],
            }
        )
        return request, email

    def _queue_if_ready(self, result: DraftResult, thread_id: str) -> Proposal:
        if result.status != "ready_for_review" or result.proposal is None:
            return Proposal(result)
        item = self.queue.submit(result.proposal.model_dump(mode="json"), thread_id)
        self.audit.record("approval.submitted", approval_id=item.id, payload_hash=item.payload_hash)
        return Proposal(result, item)

    def propose(self, email_id: str, approved_slots: list[str] | None = None) -> Proposal:
        request, email = self._request(email_id, approved_slots)
        output = draft_node({"draft_request": request.model_dump(mode="json")}, self.deps)
        result = DraftResult.model_validate(output["draft_result"])
        return self._queue_if_ready(result, email["thread_id"])

    def redraft(self, item_id: str, feedback: str) -> Proposal:
        item = self.queue.get(item_id)
        request, email = self._request(item.in_reply_to)
        result = redraft(request, feedback, item.proposal["revision"] + 1, self.deps)
        return self._queue_if_ready(result, email["thread_id"])

    def edit(self, item_id: str, subject: str, body: str, editor: str) -> DraftResult:
        """Apply a recruiter's edit to a pending draft. Approval still has to happen afterwards."""
        item = self.queue.get(item_id)
        if item.status != "pending":
            raise ApprovalError("not_pending")
        request, _ = self._request(item.in_reply_to)
        context = build_review_context(request, self.deps)
        if context is None:
            raise ApprovalError("context_unavailable")
        result = recheck_edited_draft(
            ProposedAction.model_validate(item.proposal), subject, body, context, self.deps.config
        )
        if result.proposal is not None:
            updated = self.queue.update_draft(item_id, result.proposal.model_dump(mode="json"))
            self.audit.record("approval.edited", approval_id=item_id, editor=editor, payload_hash=updated.payload_hash)
        return result

    def reject(self, item_id: str, approver: str) -> ApprovalItem:
        item = self.queue.reject(item_id, approver)
        self.audit.record("approval.rejected", approval_id=item_id, approver=approver)
        return item

    def approve(self, item_id: str, approver: str, reviewed_hash: str) -> ApprovalItem:
        """Approve the exact text the human reviewed."""
        item = self.queue.approve(item_id, approver, reviewed_hash)
        self.audit.record("approval.approved", approval_id=item_id, approver=approver, payload_hash=reviewed_hash)
        return item

    def send(self, item_id: str) -> ExecutionResult:
        return execute_approved(item_id, queue=self.queue, provider=self.mailbox, audit=self.audit)

    def approve_and_send(self, item_id: str, approver: str, reviewed_hash: str) -> ExecutionResult:
        self.approve(item_id, approver, reviewed_hash)
        return self.send(item_id)
