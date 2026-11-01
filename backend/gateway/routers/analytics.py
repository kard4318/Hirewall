# HTTP routes for People Analytics (HR only): aggregate, privacy-suppressed metrics over synthetic data
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query as Param, Request

from gateway.routers.hr_scheduling import require_hr
from services.analytics.config import CONTRACTS, DEPARTMENTS, SITES
from services.analytics.reports import AnalyticsService, Query, parse_date
from services.analytics.repository import DataMissing

router = APIRouter(prefix="/api/hr/analytics", dependencies=[Depends(require_hr)])


def service(request: Request) -> AnalyticsService:
    return request.app.state.analytics


def query(department: str | None = None, site: str | None = None, contract: str | None = None,
          from_: str | None = Param(default=None, alias="from"), to: str | None = None) -> Query:
    for value, allowed, name in ((department, DEPARTMENTS, "department"), (site, SITES, "site"), (contract, CONTRACTS, "contract")):
        if value is not None and value not in allowed:
            raise HTTPException(422, f"unknown {name}")
    try:
        return Query(department, site, contract, parse_date(from_), parse_date(to))
    except ValueError:
        raise HTTPException(422, "dates must be YYYY-MM-DD") from None


def run(fn: Any, *args: Any) -> dict[str, Any]:
    try:
        return fn(*args)
    except DataMissing as exc:
        raise HTTPException(503, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/filters")
def filters(request: Request) -> dict[str, Any]:
    return run(service(request).filters)


@router.get("/summary")
def summary(request: Request, q: Query = Depends(query)) -> dict[str, Any]:
    return run(service(request).summary, q)


@router.get("/headcount/timeseries")
def headcount_timeseries(request: Request, q: Query = Depends(query), granularity: str = "quarter") -> dict[str, Any]:
    return run(service(request).headcount_timeseries, q, granularity)


@router.get("/headcount/by")
def headcount_by(request: Request, dimension: str, q: Query = Depends(query)) -> dict[str, Any]:
    return run(service(request).headcount_by, q, dimension)


@router.get("/attrition/quarterly")
def attrition_quarterly(request: Request, q: Query = Depends(query)) -> dict[str, Any]:
    return run(service(request).attrition_quarterly, q)


@router.get("/attrition/by-department")
def attrition_by_department(request: Request, q: Query = Depends(query)) -> dict[str, Any]:
    return run(service(request).attrition_by_department, q)


@router.get("/attrition/exit-reasons")
def exit_reasons(request: Request, q: Query = Depends(query)) -> dict[str, Any]:
    return run(service(request).exit_reasons, q)


@router.get("/engagement")
def engagement(request: Request, q: Query = Depends(query)) -> dict[str, Any]:
    return run(service(request).engagement, q)


@router.get("/training")
def training(request: Request, q: Query = Depends(query)) -> dict[str, Any]:
    return run(service(request).training, q)


@router.get("/agent-activity")
def agent_activity(request: Request, weeks: int = Param(default=8, ge=1, le=26)) -> dict[str, Any]:
    return run(service(request).agent_activity, weeks)


@router.get("/recap")
def weekly_recap(request: Request, week_start: str | None = None, q: Query = Depends(query)) -> dict[str, Any]:
    try:
        start = parse_date(week_start)
    except ValueError:
        raise HTTPException(422, "week_start must be YYYY-MM-DD") from None
    return run(service(request).weekly_recap, start, q)
