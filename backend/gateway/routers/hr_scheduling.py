# HTTP routes for the HR scheduling dashboard (all behind HR auth except login)
import os
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from gateway.auth.hr_auth import HR_TOKEN_TTL_HOURS, HRAuthConfigError, HRAuthError
from gateway.auth.jwt import Principal, issue_token, read_token
from gateway.auth.roles import ROLE_AUDIENCE, can
from gateway.schemas.scheduling import HRLogin, HRToken, StrictSetting
from services.scheduler.service import Conflict, NotFound, SchedulingService

EMBED_BASE = "https://calendar.google.com/calendar/embed"


def service(request: Request) -> SchedulingService:
    return request.app.state.scheduling


def require_hr(request: Request, authorization: str = Header(default="")) -> Principal:
    """The signed-in HR user. Every decision is recorded under this name, never one sent by the client."""
    scheme, _, token = authorization.partition(" ")
    try:
        if scheme.lower() != "bearer" or not token:
            raise HRAuthError("missing token")
        principal = read_token(token, service(request).deps.clock.now(), "hr")
    except HRAuthError:
        raise HTTPException(401, "hr_auth_required", headers={"WWW-Authenticate": "Bearer"}) from None
    except HRAuthConfigError:
        raise HTTPException(503, "hr_auth_not_configured") from None
    if not can(principal.role, "hr_area"):
        raise HTTPException(403, "forbidden")
    return principal


def require_permission(permission: str):  # noqa: ANN201 - a FastAPI dependency factory
    def check(principal: Principal = Depends(require_hr)) -> Principal:
        if not can(principal.role, permission):
            raise HTTPException(403, "forbidden")
        return principal

    return check


def sign_in(request: Request, username: str, password: str, audience: str) -> tuple[str, Any]:
    """Shared by the HR and employee logins. Wrong names and passwords get the same answer, and lockouts are audited."""
    now = service(request).deps.clock.now()
    client = request.client.host if request.client else "unknown"
    if not request.app.state.login_limiter.allow(f"{audience}:{client}", now):
        raise HTTPException(429, "too_many_attempts")
    guard, audit = request.app.state.login_guard, request.app.state.audit
    name = username.strip().lower()
    if guard.locked(name, now):
        audit.record("auth.login_refused", audience=audience, reason="account_locked", user=name)
        raise HTTPException(429, "account_locked")
    user = request.app.state.users.authenticate(name, password)
    if user is None or ROLE_AUDIENCE.get(user.role) != audience:
        known = request.app.state.users.get(name) is not None
        locked = guard.failed(name, now) if known else False
        # A typed username that matches nobody may be anything, even a password: it is never recorded.
        audit.record("auth.login_failed", audience=audience, user=name if known else None)
        if locked:
            audit.record("auth.account_locked", audience=audience, user=name)
        raise HTTPException(401, "invalid_credentials")
    guard.succeeded(name)
    try:
        token = issue_token(user.username, user.role, now)
    except HRAuthConfigError:
        raise HTTPException(503, "staff_auth_not_configured") from None
    audit.record("auth.login_succeeded", audience=audience, user=user.username, role=user.role)
    return token, user


public = APIRouter()
router = APIRouter(prefix="/api/hr", dependencies=[Depends(require_hr)])


@public.post("/api/hr/login", response_model=HRToken)
def login(body: HRLogin, request: Request) -> HRToken:
    token, user = sign_in(request, body.username, body.password, "hr")
    return HRToken(token=token, expires_in_hours=HR_TOKEN_TTL_HOURS, username=user.username,
                   display_name=user.display_name, role=user.role)


@router.get("/me")
def me(request: Request, principal: Principal = Depends(require_hr)) -> dict[str, str]:
    user = request.app.state.users.get(principal.username)
    return {"username": principal.username, "role": principal.role,
            "display_name": user.display_name if user else principal.username}


@router.get("/jobs")
def jobs(request: Request) -> list[dict[str, Any]]:
    return service(request).jobs()


@router.get("/jobs/{job_id}/candidates")
def candidates(job_id: str, request: Request) -> list[dict[str, Any]]:
    try:
        return service(request).candidates(job_id)
    except NotFound:
        raise HTTPException(404, "unknown_job") from None


@router.post("/candidates/{candidate_id}/invite")
def invite(candidate_id: str, request: Request) -> dict[str, str]:
    try:
        return {"candidate_link": service(request).invite(candidate_id)}
    except NotFound:
        raise HTTPException(404, "unknown_candidate") from None
    except Conflict:
        raise HTTPException(409, "booking_in_progress") from None


@router.post("/bookings/{booking_id}/cancel")
def cancel(booking_id: str, request: Request) -> dict[str, bool]:
    try:
        service(request).cancel(booking_id)
    except NotFound:
        raise HTTPException(404, "unknown_booking") from None
    return {"ok": True}


@router.post("/bookings/{booking_id}/approve")
def approve(booking_id: str, request: Request, principal: Principal = Depends(require_permission("approve"))) -> dict[str, bool]:
    return _decide(request, booking_id, True, principal)


@router.post("/bookings/{booking_id}/decline")
def decline(booking_id: str, request: Request, principal: Principal = Depends(require_permission("approve"))) -> dict[str, bool]:
    return _decide(request, booking_id, False, principal)


def _decide(request: Request, booking_id: str, approved: bool, principal: Principal) -> dict[str, bool]:
    try:
        service(request).decide(booking_id, approved, reviewer=principal.username)
    except NotFound:
        raise HTTPException(404, "no_pending_approval") from None
    return {"ok": True}


@router.get("/settings")
def settings(request: Request) -> dict[str, bool]:
    return {"strict": service(request).deps.config.strict_booking}


@router.post("/settings/strict")
def set_strict(body: StrictSetting, request: Request) -> dict[str, bool]:
    try:
        service(request).set_strict(body.enabled)
    except Conflict:
        raise HTTPException(409, "approval_required") from None
    return {"strict": True}


@router.get("/audit")
def audit(request: Request, limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
    return service(request).audit(limit)


@router.get("/calendar-embed")
def calendar_embed() -> dict[str, Any]:
    url = build_embed_url(os.getenv("GOOGLE_CALENDAR_EMBED_ID", ""), os.getenv("GOOGLE_CALENDAR_ID", "primary"),
                          os.getenv("SCHEDULER_TIMEZONE", "Africa/Tunis"))
    return {"url": url} if url else {"url": None, "hint": "Set GOOGLE_CALENDAR_EMBED_ID"}


def build_embed_url(embed_id: str, calendar_id: str, timezone: str) -> str | None:
    """Embed URL for the HR calendar; never logged. 'primary' is not embeddable, so it needs an explicit id."""
    source = embed_id.strip() or (calendar_id.strip() if calendar_id.strip() not in ("", "primary") else "")
    if not source:
        return None
    params = {"src": source, "ctz": timezone, "mode": "WEEK", "showTitle": "0", "showPrint": "0",
              "showCalendars": "0", "showTz": "0", "bgcolor": "#F2ECDF"}
    return f"{EMBED_BASE}?{urlencode(params, quote_via=quote)}"
