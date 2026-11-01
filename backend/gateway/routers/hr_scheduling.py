# HTTP routes for the HR scheduling dashboard (all behind HR auth except login)
import os
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from gateway.auth.hr_auth import (
    HR_TOKEN_TTL_HOURS,
    HRAuthConfigError,
    HRAuthError,
    check_passcode,
    create_hr_token,
    verify_hr_token,
)
from gateway.schemas.scheduling import HRLogin, HRToken, StrictSetting
from services.scheduler.service import Conflict, NotFound, SchedulingService

EMBED_BASE = "https://calendar.google.com/calendar/embed"


def service(request: Request) -> SchedulingService:
    return request.app.state.scheduling


def require_hr(request: Request, authorization: str = Header(default="")) -> None:
    scheme, _, token = authorization.partition(" ")
    try:
        if scheme.lower() != "bearer" or not token:
            raise HRAuthError("missing token")
        verify_hr_token(token, service(request).deps.clock.now())
    except HRAuthError:
        raise HTTPException(401, "hr_auth_required", headers={"WWW-Authenticate": "Bearer"}) from None
    except HRAuthConfigError:
        raise HTTPException(503, "hr_auth_not_configured") from None


public = APIRouter()
router = APIRouter(prefix="/api/hr", dependencies=[Depends(require_hr)])


@public.post("/api/hr/login", response_model=HRToken)
def login(body: HRLogin, request: Request) -> HRToken:
    now = service(request).deps.clock.now()
    client = request.client.host if request.client else "unknown"
    if not request.app.state.login_limiter.allow(client, now):
        raise HTTPException(429, "too_many_attempts")
    try:
        if not check_passcode(body.passcode):
            raise HTTPException(401, "wrong_passcode")
        return HRToken(token=create_hr_token(now), expires_in_hours=HR_TOKEN_TTL_HOURS)
    except HRAuthConfigError:
        raise HTTPException(503, "hr_auth_not_configured") from None


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
def approve(booking_id: str, request: Request) -> dict[str, bool]:
    return _decide(request, booking_id, approved=True)


@router.post("/bookings/{booking_id}/decline")
def decline(booking_id: str, request: Request) -> dict[str, bool]:
    return _decide(request, booking_id, approved=False)


def _decide(request: Request, booking_id: str, approved: bool) -> dict[str, bool]:
    try:
        service(request).decide(booking_id, approved)
    except NotFound:
        raise HTTPException(404, "no_pending_approval") from None
    return {"ok": True}


@router.get("/settings")
def settings(request: Request) -> dict[str, bool]:
    return {"strict": service(request).deps.config.strict_booking}


@router.post("/settings/strict")
def set_strict(body: StrictSetting, request: Request) -> dict[str, bool]:
    service(request).set_strict(body.enabled)
    return {"strict": body.enabled}


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
