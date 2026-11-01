# HTTP routes for the daily inbox digest (HR only). Generation runs in the background, because a local model is slow
import logging
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from gateway.routers.hr_scheduling import require_hr
from gateway.routers.inbox import orchestrator
from orchestrator.graph import DIGEST_TASK
from services.summarizer.digest import SCOPE_ALL, valid_scope

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/hr/digest", dependencies=[Depends(require_hr)])
_jobs_lock = threading.Lock()


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str | None = Field(default=None, max_length=10)


def _scope(date: str | None) -> str:
    scope = date or SCOPE_ALL
    if not valid_scope(scope):
        raise HTTPException(422, "invalid_digest_date")
    return scope


def _jobs(request: Request) -> dict[str, dict[str, Any]]:
    if not hasattr(request.app.state, "digest_jobs"):
        request.app.state.digest_jobs = {}
    return request.app.state.digest_jobs


def _run_job(orch: Any, scope: str, jobs: dict[str, dict[str, Any]]) -> None:
    try:
        view = orch.start(scope, task=DIGEST_TASK)
        failed = view.status != "completed"
        jobs[scope] = {"state": "failed" if failed else "done", "error": view.reason_code if failed else None}
    except Exception as error:
        # Exception text can quote email content, so only its type is kept.
        logger.error("digest job failed error_type=%s", type(error).__name__)
        jobs[scope] = {"state": "failed", "error": "digest_failed"}


@router.get("")
def read_digest(request: Request, date: str | None = None) -> dict[str, Any]:
    """The latest digest for this period, using each email's current status, plus any running job."""
    scope = _scope(date)
    orch = orchestrator(request)
    return {
        "scope": scope,
        "job": _jobs(request).get(scope, {"state": "idle", "error": None}),
        "digest": orch.digest(scope),
        "saved": orch.digest_store.saved_scopes(),
    }


@router.post("/generate", status_code=202)
def generate_digest(body: GenerateRequest, request: Request) -> dict[str, Any]:
    scope = _scope(body.date)
    orch = orchestrator(request)
    jobs = _jobs(request)
    with _jobs_lock:
        if jobs.get(scope, {}).get("state") == "running":
            raise HTTPException(409, "digest_already_running")
        jobs[scope] = {"state": "running", "error": None}
    threading.Thread(target=_run_job, args=(orch, scope, jobs), daemon=True).start()
    return {"scope": scope, "job": jobs[scope]}
