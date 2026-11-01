# FastAPI application entrypoint that mounts routers and middleware
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.audit.audit_log import AuditLog, get_audit_sink
from core.integrations.email_provider import email_sender_from_env
from gateway.auth.hr_auth import LoginRateLimiter
from gateway.auth.login import LoginGuard, UserStore
from gateway.config import GatewaySettings
from gateway.middleware.cors import install_cors
from gateway.middleware.rate_limit import RateLimitMiddleware
from gateway.middleware.request_logging import RequestLoggingMiddleware
from gateway.middleware.security import BodySizeMiddleware, SecurityHeadersMiddleware, install_error_handlers
from gateway.routers import (
    analytics,
    approvals,
    audit,
    digest,
    directory,
    employee_qa,
    hr_scheduling,
    inbox,
    scheduling,
    screener,
)
from gateway.routers import candidates as candidates_router
from gateway.routers import users as users_router
from services.analytics.config import AnalyticsSettings
from services.analytics.directory import Directory
from services.analytics.reports import AnalyticsService
from services.analytics.repository import PeopleRepository
from services.employee_qa.desk import KnowledgeDesk, desk_from_env
from services.scheduler.config import REPO_ROOT
from services.scheduler.service import SchedulingService, service_from_env


class Utf8JSONResponse(JSONResponse):
    """Declare the charset explicitly so no client guesses a legacy encoding for names like 'Léa' or '×'."""

    media_type = "application/json; charset=utf-8"


def create_app(scheduling_service: SchedulingService | None = None,
               knowledge_desk: KnowledgeDesk | None = None,
               analytics_service: AnalyticsService | None = None,
               email_orchestrator: Any = None,
               screening_service: Any = None,
               users: UserStore | None = None,
               audit_log: AuditLog | None = None,
               settings: GatewaySettings | None = None) -> FastAPI:
    """App factory. Tests pass services built from fakes; with no arguments everything is built from .env."""
    if scheduling_service is None:
        load_dotenv(REPO_ROOT / ".env")
        scheduling_service = service_from_env(email_sender_from_env())
        knowledge_desk = knowledge_desk or desk_from_env(email_sender_from_env())
    app = FastAPI(title="Hirewall gateway", docs_url=None, redoc_url=None, openapi_url=None,
                  default_response_class=Utf8JSONResponse)
    app.state.scheduling = scheduling_service
    app.state.knowledge = knowledge_desk  # None in tests that only exercise scheduling
    # Reads data/people lazily, on the first analytics request.
    app.state.analytics = analytics_service or AnalyticsService(PeopleRepository(AnalyticsSettings()))
    app.state.directory = Directory(app.state.analytics.repo)  # identified records, HR only
    app.state.email_orchestrator = email_orchestrator  # drafter/classifier workflows; built lazily when None
    app.state.screening = screening_service  # resume screener; built lazily when None
    app.state.login_limiter = LoginRateLimiter()
    app.state.users = users or UserStore()  # named staff accounts (HIREWALL_USERS_FILE)
    app.state.login_guard = LoginGuard()
    app.state.audit = audit_log or get_audit_sink()  # sign-ins and security events; IDs and reason codes only
    app.state.upload_limiter = LoginRateLimiter(limit=10)

    # Added innermost first: requests pass logging, headers, CORS, size and rate checks, in that order.
    settings = settings or GatewaySettings()
    app.state.gateway_settings = settings
    app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.requests_per_minute,
                       llm_requests_per_minute=settings.llm_requests_per_minute)
    app.add_middleware(BodySizeMiddleware, limit=settings.max_body_bytes)
    install_cors(app, settings.allowed_origins)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.hsts)
    app.add_middleware(RequestLoggingMiddleware)
    install_error_handlers(app)

    app.include_router(scheduling.router)
    app.include_router(hr_scheduling.public)
    app.include_router(hr_scheduling.router)
    app.include_router(employee_qa.public)
    app.include_router(employee_qa.staff)
    app.include_router(employee_qa.hr)
    app.include_router(analytics.router)
    app.include_router(directory.router)
    app.include_router(digest.router)
    app.include_router(inbox.router)
    app.include_router(screener.router)
    app.include_router(approvals.router)
    app.include_router(audit.router)
    app.include_router(users_router.router)
    app.include_router(candidates_router.router)
    return app


if __name__ == "__main__":
    import logging

    import uvicorn

    # Request lines (gateway/middleware/request_logging.py) hold IDs, routes and status codes only.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # Candidate links are in URL paths, so the access log stays off.
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.getenv("GATEWAY_PORT", "8000")), access_log=False)
