# HTTP routes for the human approval queue
import os
import threading
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from core.approval_queue.approval_queue import ApprovalError, ApprovalItem
from gateway.auth.jwt import Principal
from gateway.orchestration import shared_orchestrator
from gateway.routers.hr_scheduling import require_hr, require_permission

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
    workflow = shared_orchestrator(request.app).workflow
    queue = workflow.queue
    notified: dict[str, list[dict[str, str]]] = {}
    for entry in workflow.audit.entries():
        if entry["event"] == "executor.notification":
            fields = entry["fields"]
            notified.setdefault(fields["approval_id"], []).append(
                {"candidate_id": fields["candidate_id"], "outcome": fields["outcome"]}
            )
    return {
        "delivery": os.getenv("EMAIL_MODE", "outbox").strip().lower(),
        "items": [
            {
                "approval_id": item.id,
                "status": item.status,
                "action_type": _action_type(item),
                "thread_id": item.thread_id,
                "payload_hash": item.payload_hash,
                "summary": _summary(item),
                "notifications": notified.get(item.id, []),
                "created_at": item.created_at,
                "decided_by": item.decided_by,
                "decided_at": item.decided_at,
            }
            for item in reversed(queue.list(status))
        ]
    }


@router.post("/{approval_id}/decision")
def decide(
    request: Request, approval_id: str, body: ApprovalDecision, principal: Principal = Depends(require_permission("approve"))
) -> dict[str, Any]:
    if body.action == "approve" and not body.reviewed_hash:
        raise HTTPException(422, "reviewed_hash_required")
    orchestrator = shared_orchestrator(request.app)
    decision: dict[str, Any] = {"action": body.action, "reviewer": principal.username}
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
