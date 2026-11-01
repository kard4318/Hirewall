# HTTP routes for candidate data rights: erase one candidate everywhere (hr_admin only, confirmed, audited)
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from gateway.auth.jwt import Principal
from gateway.erasure import ErasureBlocked, erase_everywhere
from gateway.orchestration import screening_service, shared_orchestrator
from gateway.routers.hr_scheduling import require_permission
from services.screener.service import ScreenerError

router = APIRouter(prefix="/api/hr/candidates", dependencies=[Depends(require_permission("erase_candidate"))])


class Erasure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str = Field(max_length=64)  # the candidate ID typed again


@router.post("/{candidate_id}/erase")
def erase(
    request: Request, candidate_id: str, body: Erasure,
    admin: Principal = Depends(require_permission("erase_candidate")),
) -> dict[str, Any]:
    if body.confirm != candidate_id:
        raise HTTPException(422, "confirmation_required")
    orchestrator = shared_orchestrator(request.app)
    try:
        counts = erase_everywhere(
            candidate_id, by=admin.username, screening=screening_service(request.app),
            queue=orchestrator.workflow.queue, audit=request.app.state.audit, scheduling=request.app.state.scheduling,
        )
    except ErasureBlocked as error:
        raise HTTPException(409, str(error)) from None
    except ScreenerError as error:
        raise HTTPException(404, str(error)) from None
    return {"erased": candidate_id, "removed": counts}
