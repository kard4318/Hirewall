# HTTP routes for the resume screener: uploads, jobs, scoring runs, proposals, audited identity reveal (HR only)
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from core.approval_queue.approval_queue import ApprovalError
from gateway.auth.hr_auth import LoginRateLimiter
from gateway.orchestration import screening_service, shared_orchestrator
from gateway.routers.hr_scheduling import require_hr, service
from gateway.routers.inbox import REVIEWER
from orchestrator.record_approval import RECORD_TASK
from security.file_validator import MAX_BYTES
from services.screener.models import JobPostingDetails, Requirement
from services.screener.node import SCREEN_TASK
from services.screener.service import MAX_FILES, ScreenerError

logger = logging.getLogger(__name__)

_MAX_BODY_BYTES = MAX_FILES * MAX_BYTES + 1024 * 1024
_UPLOADS_PER_MINUTE = 10
_runs = ThreadPoolExecutor(max_workers=1, thread_name_prefix="screen-job")  # the local model does one job at a time
_lock = threading.Lock()

router = APIRouter(prefix="/api/screener", dependencies=[Depends(require_hr)])


class NewJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=200)
    requirements: list[Requirement] = Field(min_length=1, max_length=40)


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_ids: list[str] = Field(min_length=1, max_length=200)
    kind: Literal["shortlist", "rejection"]


def _error(error: ScreenerError) -> HTTPException:
    code = str(error)
    return HTTPException(404 if code.endswith("_not_found") else 409, code)


def _check_upload_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    limiter: LoginRateLimiter = request.app.state.upload_limiter
    if not limiter.allow(client, service(request).deps.clock.now()):
        raise HTTPException(429, "too_many_uploads")


@router.post("/candidates", status_code=202)
async def upload(
    request: Request, files: list[UploadFile] = File(...), job_id: str | None = Form(default=None, max_length=64)
) -> dict[str, str]:
    _check_upload_limit(request)
    if not 1 <= len(files) <= MAX_FILES:
        raise HTTPException(422, "too_many_files")
    if int(request.headers.get("content-length") or 0) > _MAX_BODY_BYTES:
        raise HTTPException(413, "upload_too_large")
    # One byte over the limit is enough for the validator to refuse the file with a per-file result.
    items = [(file.filename or "", await file.read(MAX_BYTES + 1)) for file in files]
    try:
        return {"task_id": screening_service(request.app).ingest_files(items, job_id).task_id}
    except ScreenerError as error:
        raise _error(error) from None


@router.get("/tasks/{task_id}")
def task(request: Request, task_id: str) -> dict[str, Any]:
    try:
        return screening_service(request.app).get_task(task_id).model_dump(mode="json")
    except ScreenerError as error:
        raise _error(error) from None


@router.get("/candidates")
def candidates(request: Request) -> dict[str, Any]:
    rows = screening_service(request.app).list_candidates()
    return {"candidates": [row.model_dump(mode="json") for row in rows]}


@router.post("/candidates/demo", status_code=202)
def load_demo(request: Request) -> dict[str, str]:
    return {"task_id": screening_service(request.app).load_demo().task_id}


@router.get("/jobs")
def jobs(request: Request) -> dict[str, Any]:
    return {"jobs": screening_service(request.app).job_rows()}


@router.post("/jobs", status_code=201)
def create_job(request: Request, body: NewJob) -> dict[str, Any]:
    return screening_service(request.app).create_job(body.title, body.requirements).model_dump(mode="json")


@router.post("/jobs/extract", status_code=202)
async def extract_job(request: Request, file: UploadFile = File(...)) -> dict[str, str]:
    _check_upload_limit(request)
    data = await file.read(MAX_BYTES + 1)
    task, job_id = screening_service(request.app).extract_posting(file.filename or "", data)
    return {"task_id": task.task_id, "job_id": job_id}


def _posting(call: Any, *args: Any) -> dict[str, Any]:
    try:
        return call(*args).model_dump(mode="json")
    except ScreenerError as error:
        raise _error(error) from None


@router.get("/jobs/drafts/{job_id}")
def draft(request: Request, job_id: str) -> dict[str, Any]:
    return _posting(screening_service(request.app).get_posting, job_id)


@router.get("/jobs/{job_id}/posting")
def posting(request: Request, job_id: str) -> dict[str, Any]:
    return _posting(screening_service(request.app).get_posting, job_id)


@router.put("/jobs/{job_id}")
def update_posting(request: Request, job_id: str, details: JobPostingDetails) -> dict[str, Any]:
    return _posting(screening_service(request.app).update_posting, job_id, details)


@router.post("/jobs/{job_id}/publish")
def publish(request: Request, job_id: str) -> dict[str, Any]:
    return _posting(screening_service(request.app).publish_posting, job_id)


@router.post("/jobs/{job_id}/close")
def close(request: Request, job_id: str) -> dict[str, Any]:
    return _posting(screening_service(request.app).close_posting, job_id)


@router.get("/jobs/{job_id}/applications")
def applications(request: Request, job_id: str) -> dict[str, Any]:
    try:
        return {"applications": screening_service(request.app).list_applications(job_id)}
    except ScreenerError as error:
        raise _error(error) from None


@router.get("/candidates/{candidate_id}/extracted")
def extracted(request: Request, candidate_id: str) -> dict[str, Any]:
    try:
        return screening_service(request.app).get_extracted(candidate_id)
    except ScreenerError as error:
        raise _error(error) from None


def _run_in_background(orchestrator: Any, run_id: str) -> None:
    try:
        orchestrator.start(run_id, SCREEN_TASK)
    except Exception as error:
        logger.error("screen_job failed run_id=%s error_type=%s", run_id, type(error).__name__)


@router.post("/jobs/{job_id}/runs", status_code=202)
def start_run(request: Request, job_id: str) -> dict[str, str]:
    orchestrator = shared_orchestrator(request.app)
    try:
        run = screening_service(request.app).start_run(job_id)
    except ScreenerError as error:
        raise _error(error) from None
    _runs.submit(_run_in_background, orchestrator, run.run_id)
    return {"run_id": run.run_id}


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict[str, Any]:
    try:
        return screening_service(request.app).get_run(run_id).model_dump(mode="json")
    except ScreenerError as error:
        raise _error(error) from None


@router.post("/runs/{run_id}/shortlist-proposals", status_code=201)
def propose(request: Request, run_id: str, body: ProposalRequest) -> dict[str, Any]:
    orchestrator = shared_orchestrator(request.app)
    try:
        proposal_id = screening_service(request.app).prepare_proposal(run_id, body.candidate_ids, body.kind)
        with _lock:
            view = orchestrator.start(proposal_id, RECORD_TASK)
    except ScreenerError as error:
        raise _error(error) from None
    except ApprovalError as error:
        raise HTTPException(409, str(error)) from None
    if view.approval_id is None:
        raise HTTPException(409, view.reason_code or "proposal_unavailable")
    result = asdict(view)
    return {
        "proposal_id": proposal_id, "approval_id": result["approval_id"], "thread_id": result["thread_id"],
        "payload_hash": result["payload_hash"], "status": result["status"],
    }


@router.get("/candidates/{candidate_id}/identity")
def identity(request: Request, candidate_id: str) -> dict[str, Any]:
    try:
        return screening_service(request.app).reveal_identity(candidate_id, REVIEWER).model_dump(mode="json")
    except ScreenerError as error:
        raise _error(error) from None
