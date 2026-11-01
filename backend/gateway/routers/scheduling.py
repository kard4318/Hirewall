# HTTP routes for interview scheduling and follow-ups: public meta and the candidate booking conversation
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from gateway.schemas.scheduling import CandidateMessage
from services.scheduler.service import COMPANY_NAME, LinkError, SchedulingService

router = APIRouter()


def service(request: Request) -> SchedulingService:
    return request.app.state.scheduling


def dev_mode() -> bool:
    return os.getenv("DEV_MODE", "false").strip().lower() in ("1", "true", "yes")


@router.get("/api/meta")
def meta(request: Request) -> dict[str, Any]:
    return {"dev_mode": dev_mode(), "calendar_mode": service(request).calendar_mode,
            "strict_mode_available": True, "company_name": COMPANY_NAME}


@router.get("/api/schedule/{token}/state")
def conversation_state(token: str, request: Request) -> dict[str, Any]:
    try:
        return service(request).conversation(token)
    except LinkError:
        raise HTTPException(401, "invalid_link") from None


@router.post("/api/schedule/{token}/message")
def send_message(token: str, body: CandidateMessage, request: Request) -> dict[str, Any]:
    try:
        return service(request).message(token, body.text, body.ui_action())
    except LinkError:
        raise HTTPException(401, "invalid_link") from None
