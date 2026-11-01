# HTTP routes for employee HR question answering: employee login, asking, escalation, and the HR question desk
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from core.integrations.email_provider import EmailDeliveryError
from gateway.auth.hr_auth import (
    HR_TOKEN_TTL_HOURS,
    HRAuthConfigError,
    HRAuthError,
    check_passcode,
    create_role_token,
    verify_role_token,
)
from gateway.routers.hr_scheduling import require_hr
from gateway.schemas.employee_qa import Escalation, Question, Reply, StaffLogin
from services.employee_qa.desk import KnowledgeDesk, ReplyNotPossible


def desk(request: Request) -> KnowledgeDesk:
    knowledge = request.app.state.knowledge
    if knowledge is None:
        raise HTTPException(503, "knowledge_desk_not_configured")
    return knowledge


def now(request: Request):  # noqa: ANN201 - same clock as the rest of the gateway (fixed in tests)
    return request.app.state.scheduling.deps.clock.now()


def require_staff(request: Request, authorization: str = Header(default="")) -> str:
    """The asker's audience comes from the signed token, never from the request body."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        for role in ("employee", "hr"):
            try:
                verify_role_token(token, now(request), role)
                return role
            except HRAuthError:
                continue
            except HRAuthConfigError:
                raise HTTPException(503, "staff_auth_not_configured") from None
    raise HTTPException(401, "staff_auth_required", headers={"WWW-Authenticate": "Bearer"})


public = APIRouter()
staff = APIRouter(prefix="/api/knowledge")
hr = APIRouter(prefix="/api/hr/knowledge", dependencies=[Depends(require_hr)])


@public.post("/api/employee/login")
def employee_login(body: StaffLogin, request: Request) -> dict[str, Any]:
    client = request.client.host if request.client else "unknown"
    if not request.app.state.login_limiter.allow(f"employee:{client}", now(request)):
        raise HTTPException(429, "too_many_attempts")
    try:
        if not check_passcode(body.passcode, role="employee"):
            raise HTTPException(401, "wrong_passcode")
        return {"token": create_role_token("employee", now(request)), "expires_in_hours": HR_TOKEN_TTL_HOURS}
    except HRAuthConfigError:
        raise HTTPException(503, "employee_auth_not_configured") from None


@staff.post("/ask")
def ask(body: Question, request: Request, audience: str = Depends(require_staff)) -> dict[str, Any]:
    return desk(request).ask(body.question, audience=audience)


@staff.post("/questions/{entry_id}/escalate")
def escalate(entry_id: str, body: Escalation, request: Request, _: str = Depends(require_staff)) -> dict[str, bool]:
    try:
        desk(request).escalate(entry_id, body.contact.strip() if body.contact else None)
    except KeyError:
        raise HTTPException(404, "unknown_question") from None
    except ValueError:
        raise HTTPException(422, "contact_must_be_an_email") from None
    return {"ok": True}


@hr.get("/questions")
def questions(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return desk(request).log.recent(limit)


@hr.get("/escalations")
def escalations(request: Request) -> list[dict[str, Any]]:
    return desk(request).log.escalations()


@hr.get("/stats")
def stats(request: Request) -> dict[str, Any]:
    return desk(request).log.stats()


@hr.post("/questions/{entry_id}/resolve")
def resolve(entry_id: str, request: Request) -> dict[str, bool]:
    try:
        desk(request).resolve(entry_id)
    except KeyError:
        raise HTTPException(404, "no_escalation") from None
    return {"ok": True}


@hr.post("/questions/{entry_id}/reply")
def reply(entry_id: str, body: Reply, request: Request) -> dict[str, Any]:
    try:
        delivery = desk(request).reply(entry_id, body.message)
    except KeyError:
        raise HTTPException(404, "no_escalation") from None
    except ReplyNotPossible:
        raise HTTPException(409, "no_contact_to_reply_to") from None
    except ValueError:
        raise HTTPException(422, "reply_length") from None
    except EmailDeliveryError as exc:
        raise HTTPException(502, str(exc)) from None
    return {"ok": True, "delivery": delivery}
