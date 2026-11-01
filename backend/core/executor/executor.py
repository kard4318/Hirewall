# The only component allowed to send or record actions, after human approval

import logging
from dataclasses import dataclass
from typing import Any

from core.approval_queue.approval_queue import ApprovalQueue, proposal_hash
from core.integrations.email_provider import EmailProvider, OutboundEmail

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    reason: str | None = None


def execute_approved(item_id: str, *, queue: ApprovalQueue, provider: EmailProvider, audit: Any) -> ExecutionResult:
    """Send one approved email at most once, if it is still the text approved and still current."""
    item = queue.get(item_id)

    def report(status: str, reason: str | None = None) -> ExecutionResult:
        audit.record(
            "executor.outcome",
            approval_id=item_id,
            status=status,
            reason=reason,
            approver=item.decided_by,
            payload_hash=item.payload_hash,
        )
        return ExecutionResult(status, reason)

    if item.status != "approved":
        return report("refused", f"status_{item.status}")
    if proposal_hash(item.proposal) != item.payload_hash:
        return report("refused", "text_changed_after_approval")
    if provider.latest_inbound_id(item.thread_id) != item.in_reply_to:
        queue.set_status(item_id, "stale", "approved")
        return report("stale", "newer_email_in_thread")
    if not queue.claim_for_send(item_id):
        return report("refused", "reply_already_sent")

    proposal = item.proposal
    try:
        provider.send(
            OutboundEmail(
                idempotency_key=proposal["idempotency_key"],
                thread_id=item.thread_id,
                to=proposal["to"],
                subject=proposal["subject"],
                body=proposal["body"],
                in_reply_to=item.in_reply_to,
            )
        )
    except Exception as error:
        # The outcome of a failed send is unknown, so a human decides whether to try again.
        logger.error("send failed error_type=%s", type(error).__name__)
        queue.set_status(item_id, "send_failed", "sending")
        return report("send_failed", type(error).__name__)

    queue.set_status(item_id, "sent", "sending")
    return report("sent")
