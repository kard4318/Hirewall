# Builds every analytics response: filters, periods, privacy suppression and "as_of" on all outputs
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from services.analytics import metrics, recap
from services.analytics.config import (
    AGE_BANDS,
    CONTRACTS,
    DEPARTMENTS,
    GENDERS,
    MINUTES_SAVED,
    SITES,
    TENURE_BANDS,
    AnalyticsSettings,
)
from services.analytics.models import AuditEvent, Employee
from services.analytics.privacy import SUPPRESSED, suppress_groups, suppress_value
from services.analytics.repository import PeopleRepository

DIMENSIONS = {"department": DEPARTMENTS, "site": SITES, "contract": CONTRACTS, "age_band": AGE_BANDS,
              "gender": GENDERS, "tenure_band": TENURE_BANDS}
EXIT_REASONS = ["career_growth", "compensation", "management", "relocation", "personal", "performance",
                "restructuring", "retirement"]


@dataclass(frozen=True)
class Query:
    department: str | None = None
    site: str | None = None
    contract: str | None = None
    start: date | None = None
    end: date | None = None


def _r(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _tile(current: float | None, previous: float | None, digits: int = 4) -> dict[str, Any]:
    return {"value": _r(current, digits), "previous": _r(previous, digits), "delta": _r(metrics.delta(current, previous), digits)}


def hours_saved(events: list[AuditEvent]) -> float:
    minutes = 0
    for e in events:
        minutes += MINUTES_SAVED.get((e.event, e.outcome), MINUTES_SAVED.get((e.event, None), 0))
    return round(minutes / 60, 1)


def week_start_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


class AnalyticsService:
    def __init__(self, repository: PeopleRepository) -> None:
        self.repo = repository
        self.settings: AnalyticsSettings = repository.settings

    # --- shared helpers -----------------------------------------------------------------------------------
    def period(self, q: Query) -> tuple[date, date]:
        end = min(q.end or self.settings.as_of, self.settings.as_of)
        start = q.start or end - timedelta(days=365)
        if start > end:
            raise ValueError("from must be on or before to")
        return start, end

    def previous_period(self, start: date, end: date) -> tuple[date, date]:
        prev_end = start - timedelta(days=1)
        return prev_end - (end - start), prev_end

    def population(self, q: Query, ignore_department: bool = False) -> list[Employee]:
        return metrics.filter_employees(self.repo.employees(), None if ignore_department else q.department, q.site, q.contract)

    def envelope(self, q: Query, **body: Any) -> dict[str, Any]:
        start, end = self.period(q)
        return {"as_of": self.settings.as_of.isoformat(), "period": {"from": start.isoformat(), "to": end.isoformat()},
                "filters": {"department": q.department, "site": q.site, "contract": q.contract},
                "min_group_size": self.settings.min_group_size, **body}

    def events_between(self, start: date, end: date) -> list[AuditEvent]:
        return [e for e in self.repo.audit_events() if start <= e.ts.date() <= end]

    # --- endpoints ------------------------------------------------------------------------------------------
    def filters(self) -> dict[str, Any]:
        employees = self.repo.employees()
        return {"as_of": self.settings.as_of.isoformat(), "departments": DEPARTMENTS, "sites": SITES,
                "contracts": CONTRACTS, "dimensions": list(DIMENSIONS),
                "earliest": min(e.hire_date for e in employees).isoformat(), "latest": self.settings.as_of.isoformat(),
                "min_group_size": self.settings.min_group_size, "synthetic": True}

    def summary(self, q: Query) -> dict[str, Any]:
        start, end = self.period(q)
        p_start, p_end = self.previous_period(start, end)
        people = self.population(q)
        min_size = self.settings.min_group_size
        tiles: dict[str, Any] = {}
        if metrics.headcount(people, end) < min_size:
            for name in ("headcount", "hires", "exits", "attrition_rate_12m", "avg_tenure_years", "voluntary_share",
                         "latest_engagement", "training_completion"):
                tiles[name] = dict(SUPPRESSED)
        else:
            tiles["headcount"] = _tile(metrics.headcount(people, end), metrics.headcount(people, p_end))
            tiles["hires"] = _tile(len(metrics.hires(people, start, end)), len(metrics.hires(people, p_start, p_end)))
            tiles["exits"] = _tile(len(metrics.exits(people, start, end)), len(metrics.exits(people, p_start, p_end)))
            tiles["attrition_rate_12m"] = _tile(metrics.attrition_rate_12m(people, end), metrics.attrition_rate_12m(people, p_end))
            tiles["avg_tenure_years"] = _tile(metrics.avg_tenure_years(people, end), metrics.avg_tenure_years(people, p_end), 2)
            tiles["voluntary_share"] = _tile(metrics.voluntary_share(metrics.exits(people, start, end)),
                                             metrics.voluntary_share(metrics.exits(people, p_start, p_end)))
            latest = metrics.latest_complete_quarter(end)
            before = metrics.previous_quarters(latest, 2)[0]
            eng = [r for r in self.repo.engagement() if (not q.department or r.department == q.department)
                   and (not q.site or r.site == q.site)]
            now_score, now_n = metrics.engagement_score(r for r in eng if r.quarter == latest)
            prev_score, _ = metrics.engagement_score(r for r in eng if r.quarter == before)
            tiles["latest_engagement"] = {**_tile(now_score, prev_score, 2), "quarter": latest} if now_n >= min_size else dict(SUPPRESSED)
            active = {e.employee_id for e in people if metrics.is_active(e, end)}
            completion, _, n = metrics.training_completion(r for r in self.repo.training() if r.employee_id in active)
            tiles["training_completion"] = _tile(completion, None) if n >= min_size else dict(SUPPRESSED)
        positions = [p for p in self.repo.positions() if p.status == "open" and (not q.department or p.department == q.department)]
        tiles["open_roles"] = _tile(len(positions), None)
        recent, before = self.events_between(end - timedelta(days=27), end), self.events_between(end - timedelta(days=55), end - timedelta(days=28))
        tiles["hours_saved_estimate"] = {**_tile(hours_saved(recent), hours_saved(before), 1), "window_days": 28}
        booked = lambda events: sum(e.event == "booking_created" for e in events)  # noqa: E731
        tiles["interviews_booked_30d"] = _tile(booked(self.events_between(end - timedelta(days=29), end)),
                                               booked(self.events_between(end - timedelta(days=59), end - timedelta(days=30))))
        return self.envelope(q, previous_period={"from": p_start.isoformat(), "to": p_end.isoformat()}, tiles=tiles)

    def headcount_timeseries(self, q: Query, granularity: str = "quarter") -> dict[str, Any]:
        start, end = self.period(q)
        people = self.population(q)
        points = []
        for label in self._buckets(start, end, granularity):
            b_start, b_end = label[1], min(label[2], end)
            hc = metrics.headcount(people, b_end)
            points.append({"label": label[0], "end": b_end.isoformat(),
                           **suppress_value(hc, self.settings.min_group_size, {
                               "headcount": hc, "hires": len(metrics.hires(people, b_start, b_end)),
                               "exits": len(metrics.exits(people, b_start, b_end))})})
        return self.envelope(q, granularity=granularity, points=points)

    def headcount_by(self, q: Query, dimension: str) -> dict[str, Any]:
        if dimension not in DIMENSIONS:
            raise ValueError("unknown dimension")
        _, end = self.period(q)
        active = [e for e in self.population(q) if metrics.is_active(e, end)]
        key = (lambda e: metrics.tenure_band(e, end)) if dimension == "tenure_band" else (lambda e: getattr(e, dimension))
        counts = Counter(key(e) for e in active)
        total = len(active)
        groups = [{"key": k, "n": counts[k], "share": round(counts[k] / total, 4) if total else None}
                  for k in DIMENSIONS[dimension] if counts[k]]
        if total < self.settings.min_group_size:
            return self.envelope(q, dimension=dimension, total=dict(SUPPRESSED), groups=[])
        return self.envelope(q, dimension=dimension, total={"n": total},
                             groups=suppress_groups(groups, self.settings.min_group_size))

    def attrition_quarterly(self, q: Query) -> dict[str, Any]:
        start, end = self.period(q)
        people = self.population(q)
        rows = []
        for label in metrics.quarters_between(start, end):
            q_start, q_end = metrics.quarter_bounds(label)
            q_end = min(q_end, end)
            n = metrics.average_headcount(people, q_start, q_end)
            leavers = metrics.exits(people, q_start, q_end)
            rows.append({"quarter": label, "partial": q_end < metrics.quarter_bounds(label)[1],
                         **suppress_value(round(n), self.settings.min_group_size, {
                             "rate": _r(metrics.attrition_rate(people, q_start, q_end)), "exits": len(leavers),
                             "voluntary": sum(e.exit_type == "voluntary" for e in leavers),
                             "involuntary": sum(e.exit_type in ("involuntary", "retirement") for e in leavers)})})
        complete = metrics.latest_complete_quarter(end)
        return self.envelope(q, quarters=rows,
                             company_quarterly_average=_r(metrics.company_quarterly_average(people, complete)))

    def attrition_by_department(self, q: Query) -> dict[str, Any]:
        start, end = self.period(q)
        people = self.population(q, ignore_department=True)
        min_size = self.settings.min_group_size
        departments = []
        for dept in DEPARTMENTS:
            group = metrics.filter_employees(people, department=dept)
            n = metrics.average_headcount(group, start, end)
            leavers = metrics.exits(group, start, end)
            departments.append({"key": dept, **suppress_value(round(n), min_size, {
                "rate": _r(metrics.attrition_rate(group, start, end)), "exits": len(leavers),
                "voluntary_share": _r(metrics.voluntary_share(leavers))})})
        quarters = metrics.quarters_between(start, end)
        matrix = []
        for dept in DEPARTMENTS:
            group = metrics.filter_employees(people, department=dept)
            cells = []
            for label in quarters:
                q_start, q_end = metrics.quarter_bounds(label)
                q_end = min(q_end, end)
                n = metrics.average_headcount(group, q_start, q_end)
                cells.append({"quarter": label, **suppress_value(round(n), min_size, {
                    "rate": _r(metrics.attrition_rate(group, q_start, q_end)),
                    "exits": len(metrics.exits(group, q_start, q_end))})})
            matrix.append({"department": dept, "cells": cells})
        return self.envelope(q, departments=departments, quarters=quarters, matrix=matrix)

    def exit_reasons(self, q: Query) -> dict[str, Any]:
        start, end = self.period(q)
        leavers = metrics.exits(self.population(q), start, end)
        counts = Counter(e.exit_reason for e in leavers)
        groups = [{"key": r, "n": counts[r], "share": round(counts[r] / len(leavers), 4)} for r in EXIT_REASONS if counts[r]]
        types = Counter(e.exit_type for e in leavers)
        type_groups = [{"key": t, "n": types[t]} for t in ("voluntary", "involuntary", "retirement") if types[t]]
        min_size = self.settings.min_group_size
        if len(leavers) < min_size:
            return self.envelope(q, total=dict(SUPPRESSED), reasons=[], types=[])
        return self.envelope(q, total={"n": len(leavers)}, reasons=suppress_groups(groups, min_size),
                             types=suppress_groups(type_groups, min_size))

    def engagement(self, q: Query) -> dict[str, Any]:
        start, end = self.period(q)
        rows = [r for r in self.repo.engagement() if not q.site or r.site == q.site]
        quarters = [label for label in metrics.quarters_between(start, end) if metrics.quarter_bounds(label)[1] <= end]
        min_size = self.settings.min_group_size
        company = []
        for label in quarters:
            score, n = metrics.engagement_score(r for r in rows if r.quarter == label and (not q.department or r.department == q.department))
            company.append({"quarter": label, **suppress_value(n, min_size, {"score": _r(score, 2)})})
        departments = []
        for dept in DEPARTMENTS if not q.department else [q.department]:
            series = []
            for label in quarters:
                score, n = metrics.engagement_score(r for r in rows if r.quarter == label and r.department == dept)
                series.append({"quarter": label, **suppress_value(n, min_size, {"score": _r(score, 2)})})
            departments.append({"department": dept, "series": series})
        sites = []
        for site in SITES:
            score, n = metrics.engagement_score(r for r in self.repo.engagement() if r.site == site and r.quarter in quarters
                                                and (not q.department or r.department == q.department))
            sites.append({"key": site, **suppress_value(n, min_size, {"score": _r(score, 2)})})
        return self.envelope(q, quarters=quarters, company=company, departments=departments, sites=sites)

    def training(self, q: Query) -> dict[str, Any]:
        _, end = self.period(q)
        dept_of = {e.employee_id: e.department for e in self.population(q, ignore_department=True) if metrics.is_active(e, end)}
        rows = [r for r in self.repo.training() if r.employee_id in dept_of]
        min_size = self.settings.min_group_size
        departments = []
        for dept in DEPARTMENTS if not q.department else [q.department]:
            completion, hours, n = metrics.training_completion(r for r in rows if dept_of[r.employee_id] == dept)
            departments.append({"key": dept, **suppress_value(n, min_size, {"completion": _r(completion),
                                                                             "hours_per_person": _r(hours, 1)})})
        completion, hours, n = metrics.training_completion(rows)
        return self.envelope(q, company=suppress_value(n, min_size, {"completion": _r(completion), "hours_per_person": _r(hours, 1)}),
                             departments=departments)

    def agent_activity(self, weeks: int = 8) -> dict[str, Any]:
        as_of = self.settings.as_of
        first = week_start_of(as_of) - timedelta(weeks=weeks - 1)
        events = self.events_between(first, as_of)
        series = []
        for w in range(weeks):
            start = first + timedelta(weeks=w)
            week = [e for e in events if start <= e.ts.date() <= start + timedelta(days=6)]
            series.append({"week_start": start.isoformat(), "counts": dict(Counter(e.event for e in week)),
                           "hours_saved": hours_saved(week)})
        outcome = Counter((e.event, e.outcome) for e in events)
        return {"as_of": as_of.isoformat(), "weeks": series, "synthetic": any(e.synthetic for e in events),
                "approvals": {k: outcome[("approval_decided", k)] for k in ("approve", "edit", "reject")},
                "qa": {k: outcome[("kb_question", k)] for k in ("answered", "escalated")},
                "blocked_by_reason": dict(Counter(e.reason_code for e in events if e.event == "message_blocked")),
                "hours_saved": hours_saved(events)}

    def weekly_recap(self, week_start: date | None, q: Query) -> dict[str, Any]:
        as_of = self.settings.as_of
        start = week_start_of(week_start or as_of)
        events = self.events_between(start, start + timedelta(days=6))
        p_start, _ = self.period(q)
        notes = recap.highlights(metrics.filter_employees(self.repo.employees(), site=q.site, contract=q.contract),
                                 self.repo.engagement(), self.repo.training(), as_of, p_start, self.settings.min_group_size)
        return {"as_of": as_of.isoformat(), "week_start": start.isoformat(),
                "week_end": (start + timedelta(days=6)).isoformat(), "synthetic": any(e.synthetic for e in events),
                "sentences": recap.recap_sentences(events), "hours_saved": hours_saved(events), "highlights": notes}

    # --- buckets ------------------------------------------------------------------------------------------
    @staticmethod
    def _buckets(start: date, end: date, granularity: str) -> list[tuple[str, date, date]]:
        if granularity == "quarter":
            return [(label, *metrics.quarter_bounds(label)) for label in metrics.quarters_between(start, end)]
        if granularity == "month":
            buckets, current = [], date(start.year, start.month, 1)
            while current <= end:
                nxt = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
                buckets.append((current.strftime("%Y-%m"), current, nxt - timedelta(days=1)))
                current = nxt
            return buckets
        raise ValueError("granularity must be quarter or month")


def parse_date(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None
