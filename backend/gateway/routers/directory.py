# HTTP routes for the HR employee directory (HR auth only): search and individual records with fictional names
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from gateway.routers.hr_scheduling import require_hr
from services.analytics.config import CONTRACTS, DEPARTMENTS, SITES
from services.analytics.directory import Directory, NotFound
from services.analytics.repository import DataMissing

router = APIRouter(prefix="/api/hr/directory", dependencies=[Depends(require_hr)])


def directory(request: Request) -> Directory:
    return request.app.state.directory


@router.get("")
def search(request: Request, q: str = Query(default="", max_length=80), department: str | None = None,
           site: str | None = None, contract: str | None = None, status: str = "active",
           page: int = Query(default=1, ge=1, le=1000)) -> dict[str, Any]:
    for value, allowed, name in ((department, DEPARTMENTS, "department"), (site, SITES, "site"), (contract, CONTRACTS, "contract")):
        if value is not None and value not in allowed:
            raise HTTPException(422, f"unknown {name}")
    if status not in ("active", "left", "all"):
        raise HTTPException(422, "status must be active, left or all")
    try:
        return directory(request).search(q, department, site, contract, status, page)
    except DataMissing as exc:
        raise HTTPException(503, str(exc)) from None


@router.get("/{employee_id}")
def record(employee_id: str, request: Request) -> dict[str, Any]:
    try:
        return directory(request).record(employee_id)
    except NotFound:
        raise HTTPException(404, "unknown_employee") from None
    except DataMissing as exc:
        raise HTTPException(503, str(exc)) from None
