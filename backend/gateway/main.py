# FastAPI application entrypoint that mounts routers and middleware
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request

from gateway.auth.hr_auth import LoginRateLimiter
from gateway.routers import (
    analytics,
    approvals,
    audit,
    digest,
    directory,
    employee_qa,
    hr_scheduling,
    inbox,
    jobs,
    scheduling,
    screener,
)
from services.analytics.config import AnalyticsSettings
from services.analytics.directory import Directory
from services.analytics.reports import AnalyticsService
from services.analytics.repository import PeopleRepository
from services.employee_qa.desk import KnowledgeDesk, desk_from_env
from services.scheduler.config import REPO_ROOT
from services.scheduler.service import SchedulingService, service_from_env


def create_app(scheduling_service: SchedulingService | None = None,
               knowledge_desk: KnowledgeDesk | None = None,
               analytics_service: AnalyticsService | None = None,
               email_orchestrator: Any = None,
               screening_service: Any = None) -> FastAPI:
    """App factory. Tests pass services built from fakes; with no arguments everything is built from .env."""
    if scheduling_service is None:
        load_dotenv(REPO_ROOT / ".env")
        scheduling_service = service_from_env()
        knowledge_desk = knowledge_desk or desk_from_env()
    app = FastAPI(title="Hirewall gateway", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.scheduling = scheduling_service
    app.state.knowledge = knowledge_desk  # None in tests that only exercise scheduling
    # Reads data/people lazily, on the first analytics request.
    app.state.analytics = analytics_service or AnalyticsService(PeopleRepository(AnalyticsSettings()))
    app.state.directory = Directory(app.state.analytics.repo)  # identified records, HR only
    app.state.email_orchestrator = email_orchestrator  # drafter/classifier workflows; built lazily when None
    app.state.screening = screening_service  # resume screener; built lazily when None
    app.state.login_limiter = LoginRateLimiter()
    app.state.upload_limiter = LoginRateLimiter(limit=10)
    app.state.apply_limiter = LoginRateLimiter(limit=5)  # public: must not use up HR's upload limit

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"  # responses carry personal data and booking links
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

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
    app.include_router(jobs.public)
    app.include_router(approvals.router)
    app.include_router(audit.router)
    return app


if __name__ == "__main__":
    import uvicorn

    # Candidate links are in URL paths, so the access log stays off.
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.getenv("GATEWAY_PORT", "8000")), access_log=False)
