# HTTP routes for the recruiter inbox: list emails, triage, draft replies, human decisions, sent mail (HR only)
import threading
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from core.approval_queue.approval_queue import ApprovalError
from gateway.routers.hr_scheduling import require_hr
from orchestrator.graph import TRIAGE_TASK, Orchestrator, draft_thread_id

REVIEWER = "HR desk"  # the passcode login has no personal identity; every decision is still a human one
_lock = threading.Lock()  # the approval queue and graph run one job at a time

router = APIRouter(prefix="/api/hr/inbox", dependencies=[Depends(require_hr)])


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "edit", "redraft", "reject"]
    reviewed_hash: str | None = Field(default=None, max_length=128)  # the payload_hash the reviewer saw
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=10000)
    feedback: str | None = Field(default=None, max_length=1000)


def orchestrator(request: Request) -> Orchestrator:
    """Built on first use, so the gateway starts even when the email service is not configured."""
    if request.app.state.email_orchestrator is None:
        with _lock:
            if request.app.state.email_orchestrator is None:
                request.app.state.email_orchestrator = Orchestrator()
    return request.app.state.email_orchestrator


def _views(orch: Orchestrator, email_id: str) -> dict[str, Any]:
    triage, draft = orch.view(f"{TRIAGE_TASK}:{email_id}"), orch.view(draft_thread_id(email_id))
    active = next((v for v in (triage, draft) if v.waiting_for_human), None)
    return {"triage": asdict(triage), "draft": asdict(draft), "active": asdict(active) if active else None,
            "classification": triage.classification}


def _pending_draft(orch: Orchestrator, active: dict[str, Any] | None) -> dict[str, Any] | None:
    if not active or not active.get("approval_id"):
        return None
    item = orch.workflow.queue.get(active["approval_id"])
    p = item.proposal
    return {"approval_id": item.id, "status": item.status, "payload_hash": item.payload_hash, "to": p["to"],
            "subject": p["subject"], "body": p["body"], "warnings": p.get("warnings", []),
            "claims": p.get("claims", []), "revision": p.get("revision")}


def _error(exc: ApprovalError) -> HTTPException:
    code = str(exc)
    return HTTPException(404 if code in ("email_not_found", "not_found") else 409, code)


@router.get("")
def inbox(request: Request) -> list[dict[str, Any]]:
    orch = orchestrator(request)
    with _lock:
        rows = []
        for email in reversed(orch.workflow.mailbox.inbound()):
            views = _views(orch, email["email_id"])
            rows.append({"email_id": email["email_id"], "thread_id": email["thread_id"], "from": email["from_address"],
                         "subject": email["subject"], "received_at": email["received_at"],
                         "preview": " ".join(email["body"].split())[:140], "triage_status": views["triage"]["status"],
                         "draft_status": (views["active"] or views["draft"])["status"],
                         "waiting_for_human": views["active"] is not None, "classification": views["classification"]})
        return rows


@router.get("/sent")
def sent(request: Request) -> list[dict[str, Any]]:
    with _lock:
        return list(reversed(orchestrator(request).workflow.mailbox.outbox()))


@router.get("/{email_id}")
def email_detail(email_id: str, request: Request) -> dict[str, Any]:
    orch = orchestrator(request)
    with _lock:
        email = orch.workflow.mailbox.get(email_id)
        if email is None:
            raise HTTPException(404, "email_not_found")
        views = _views(orch, email_id)
        return {"email": email, "history": orch.workflow.mailbox.thread_history(email), **views,
                "pending_draft": _pending_draft(orch, views["active"])}


@router.post("/{email_id}/triage")
def triage(email_id: str, request: Request) -> dict[str, Any]:
    return _start(request, email_id, TRIAGE_TASK)


@router.post("/{email_id}/draft")
def draft(email_id: str, request: Request) -> dict[str, Any]:
    return _start(request, email_id, "draft_reply")


def _start(request: Request, email_id: str, task: str) -> dict[str, Any]:
    orch = orchestrator(request)
    with _lock:
        if orch.workflow.mailbox.get(email_id) is None:
            raise HTTPException(404, "email_not_found")
        try:
            return asdict(orch.start(email_id, task=task))
        except ApprovalError as exc:
            raise _error(exc) from None


@router.post("/{email_id}/decision")
def decide(email_id: str, body: Decision, request: Request) -> dict[str, Any]:
    orch = orchestrator(request)
    decision: dict[str, Any] = {"action": body.action, "reviewer": REVIEWER}
    if body.action == "approve":
        if not body.reviewed_hash:
            raise HTTPException(422, "reviewed_hash_required")
        decision["reviewed_hash"] = body.reviewed_hash
    elif body.action == "edit":
        if not (body.subject and body.body):
            raise HTTPException(422, "subject_and_body_required")
        decision.update(subject=body.subject, body=body.body)
    elif body.action == "redraft":
        decision["feedback"] = (body.feedback or "").strip() or "Please rewrite this reply."
    with _lock:
        try:
            thread_id = orch.paused_thread_for_email(email_id)
            return asdict(orch.resume(thread_id, decision))
        except ApprovalError as exc:
            raise _error(exc) from None
