# HTTP routes for job offers: the public list and applications (no login)
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from gateway.auth.hr_auth import LoginRateLimiter
from gateway.orchestration import screening_service
from gateway.routers.hr_scheduling import service
from security.file_validator import MAX_BYTES
from services.screener.service import ScreenerError

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}$")
_MAX_BODY_BYTES = 2 * MAX_BYTES + 64 * 1024

public = APIRouter(prefix="/api/jobs")


def _error(error: ScreenerError) -> HTTPException:
    code = str(error)
    if code == "try_later":
        return HTTPException(429, code)
    if code.startswith(("cv_", "cover_letter_")):
        return HTTPException(422, code)
    return HTTPException(404 if code.endswith("_not_found") else 409, code)


@public.get("")
def list_offers(request: Request) -> dict[str, Any]:
    return {"jobs": screening_service(request.app).public_postings()}


@public.get("/{job_id}")
def offer(request: Request, job_id: str) -> dict[str, Any]:
    try:
        return screening_service(request.app).public_posting(job_id)
    except ScreenerError as error:
        raise _error(error) from None


async def _read_file(value: Any) -> tuple[str, bytes] | None:
    if not isinstance(value, UploadFile) or not value.filename:
        return None
    # One byte over the limit is enough for the validator to refuse the file.
    return value.filename, await value.read(MAX_BYTES + 1)


@public.post("/{job_id}/applications", status_code=202)
async def apply(request: Request, job_id: str) -> dict[str, str]:
    """Returns only a reference. An applicant never sees what was extracted or how they scored."""
    limiter: LoginRateLimiter = request.app.state.apply_limiter
    client = request.client.host if request.client else "unknown"
    if not limiter.allow(client, service(request).deps.clock.now()):
        raise HTTPException(429, "too_many_applications")
    # Checked by hand before the body is read, because nobody has logged in here.
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise HTTPException(411, "length_required")
    if int(length) > _MAX_BODY_BYTES:
        raise HTTPException(413, "upload_too_large")

    screening = screening_service(request.app)
    try:
        screening.public_posting(job_id)
    except ScreenerError as error:
        raise _error(error) from None

    form = await request.form(max_files=2, max_fields=4)
    if form.get("consent") not in ("true", "on"):
        raise HTTPException(422, "consent_required")
    full_name = " ".join(str(form.get("full_name") or "").split())
    if not 2 <= len(full_name) <= 200:
        raise HTTPException(422, "invalid_name")
    email = str(form.get("email") or "").strip()
    if len(email) > 254 or not _EMAIL.match(email):
        raise HTTPException(422, "invalid_email")
    cv = await _read_file(form.get("cv"))
    if cv is None:
        raise HTTPException(422, "cv_required")
    cover_letter = await _read_file(form.get("cover_letter"))

    try:
        await run_in_threadpool(screening.check_application_files, cv, cover_letter)
        reference_id = await run_in_threadpool(screening.submit_application, job_id, cv, cover_letter, full_name, email)
    except ScreenerError as error:
        raise _error(error) from None
    return {"reference_id": reference_id}
