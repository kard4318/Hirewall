# The only component allowed to send or record actions, after human approval

import logging
from dataclasses import dataclass
from typing import Any

from core.approval_queue.approval_queue import ApprovalQueue, proposal_hash
from core.candidate_status.store import CandidateStatusStore
from core.integrations.email_provider import EmailProvider, OutboundEmail

logger = logging.getLogger(__name__)

RECORDED_STATUS = {"record_shortlist": "shortlisted", "record_rejection": "rejected"}


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

    if item.proposal.get("action_type", "send_email") != "send_email":
        return report("refused", "unsupported_action")
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


def execute_record(
    item_id: str, *, queue: ApprovalQueue, status_store: CandidateStatusStore, audit: Any, notifier: Any = None
) -> ExecutionResult:
    """Record one approved shortlist or rejection at most once, then tell each candidate whose status changed."""
    item = queue.get(item_id)

    def report(status: str, reason: str | None = None) -> ExecutionResult:
        audit.record(
            "executor.outcome",
            approval_id=item_id,
            action_type=item.proposal.get("action_type"),
            status=status,
            reason=reason,
            approver=item.decided_by,
            payload_hash=item.payload_hash,
        )
        return ExecutionResult(status, reason)

    status = RECORDED_STATUS.get(item.proposal.get("action_type", ""))
    if status is None:
        return report("refused", "unsupported_action")
    if item.status != "approved":
        return report("refused", f"status_{item.status}")
    if proposal_hash(item.proposal) != item.payload_hash:
        return report("refused", "text_changed_after_approval")
    if not queue.claim_for_send(item_id):
        return report("refused", "already_claimed")

    payload = item.proposal["payload"]
    try:
        previous = status_store.statuses_for(payload["job_id"])
        status_store.record(payload["job_id"], payload["candidate_ids"], status, item_id)
    except Exception as error:
        logger.error("record failed error_type=%s", type(error).__name__)
        queue.set_status(item_id, "record_failed", "sending")
        return report("record_failed", type(error).__name__)

    queue.set_status(item_id, "recorded", "sending")
    result = report("recorded")
    if notifier is not None:
        for candidate_id in payload["candidate_ids"]:
            if previous.get(candidate_id) != status:
                _notify(notifier, item_id, item.proposal["action_type"], payload, candidate_id, audit)
    return result


def _notify(notifier: Any, item_id: str, action_type: str, payload: dict[str, Any], candidate_id: str, audit: Any) -> None:
    """The decision stands whatever happens here. A failed message is reported, never retried: it may have gone out."""
    try:
        outcome = notifier.notify(action_type, payload, candidate_id)
    except Exception as error:
        logger.error("notification failed error_type=%s", type(error).__name__)
        outcome = "failed"
    audit.record(
        "executor.notification", approval_id=item_id, action_type=action_type, candidate_id=candidate_id, outcome=outcome
    )
