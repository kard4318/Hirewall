# HTTP routes for the human approval queue
import threading
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from core.approval_queue.approval_queue import ApprovalError, ApprovalItem
from gateway.orchestration import shared_orchestrator
from gateway.routers.hr_scheduling import require_hr
from gateway.routers.inbox import REVIEWER

_lock = threading.Lock()

router = APIRouter(prefix="/api/hr/approvals", dependencies=[Depends(require_hr)])


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject"]
    reviewed_hash: str | None = Field(default=None, max_length=128)  # the payload_hash the reviewer saw


def _action_type(item: ApprovalItem) -> str:
    return item.proposal.get("action_type", "send_email")


def _summary(item: ApprovalItem) -> dict[str, Any]:
    """IDs only. An email's text and address stay in the inbox page."""
    return item.proposal["payload"] if "payload" in item.proposal else {"in_reply_to": item.in_reply_to}


@router.get("")
def approvals(request: Request, status: str | None = Query(default=None, max_length=30)) -> dict[str, Any]:
    queue = shared_orchestrator(request.app).workflow.queue
    return {
        "items": [
            {
                "approval_id": item.id,
                "status": item.status,
                "action_type": _action_type(item),
                "thread_id": item.thread_id,
                "payload_hash": item.payload_hash,
                "summary": _summary(item),
                "created_at": item.created_at,
                "decided_by": item.decided_by,
                "decided_at": item.decided_at,
            }
            for item in reversed(queue.list(status))
        ]
    }


@router.post("/{approval_id}/decision")
def decide(request: Request, approval_id: str, body: ApprovalDecision) -> dict[str, Any]:
    if body.action == "approve" and not body.reviewed_hash:
        raise HTTPException(422, "reviewed_hash_required")
    orchestrator = shared_orchestrator(request.app)
    decision: dict[str, Any] = {"action": body.action, "reviewer": REVIEWER}
    if body.action == "approve":
        decision["reviewed_hash"] = body.reviewed_hash
    try:
        with _lock:
            item = orchestrator.workflow.queue.get(approval_id)
            is_email = _action_type(item) == "send_email"
            thread_id = orchestrator.paused_thread_for_email(item.in_reply_to) if is_email else item.thread_id
            return asdict(orchestrator.resume(thread_id, decision))
    except ApprovalError as error:
        code = str(error)
        raise HTTPException(404 if code == "not_found" else 409, code) from None
