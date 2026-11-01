# HTTP routes for the audit log
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from gateway.orchestration import shared_orchestrator
from gateway.routers.hr_scheduling import require_hr

router = APIRouter(prefix="/api/hr/audit-log", dependencies=[Depends(require_hr)])


@router.get("")
def audit(request: Request, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    """Newest first. Audit events hold IDs, hashes and outcomes only."""
    log = shared_orchestrator(request.app).workflow.audit
    return {"entries": list(reversed(log.entries()))[:limit], "verified": log.verify()}
