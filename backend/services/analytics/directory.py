# HR employee directory: identified records (fictional names) for HR only; demographics are never shown per person
import csv
from datetime import date
from typing import Any

from services.analytics import metrics
from services.analytics.models import Employee
from services.analytics.repository import DataMissing, PeopleRepository

PAGE_SIZE = 25


class NotFound(Exception):
    pass


class Directory:
    """Joins the pseudonymous workforce data with data/people/directory.csv. Analytics endpoints never use this."""

    def __init__(self, repository: PeopleRepository) -> None:
        self.repo = repository
        self._names: tuple[float, dict[str, dict[str, str]]] | None = None

    def names(self) -> dict[str, dict[str, str]]:
        path = self.repo.settings.people_dir / "directory.csv"
        if not path.is_file():
            raise DataMissing("directory.csv not found: run `python scripts/generate_people_data.py` first.")
        mtime = path.stat().st_mtime
        if not self._names or self._names[0] != mtime:
            with path.open(encoding="utf-8", newline="") as handle:
                self._names = (mtime, {row["employee_id"]: row for row in csv.DictReader(handle)})
        return self._names[1]

    def _card(self, e: Employee, names: dict[str, dict[str, str]], as_of: date) -> dict[str, Any]:
        person = names.get(e.employee_id, {})
        active = metrics.is_active(e, as_of)
        return {
            "employee_id": e.employee_id,
            "name": f"{person.get('first_name', '')} {person.get('last_name', '')}".strip() or e.employee_id,
            "email": person.get("email"),
            "department": e.department, "job_title": e.job_title, "level": e.level, "site": e.site,
            "contract": e.contract, "hire_date": e.hire_date.isoformat(),
            "status": "active" if active else ("left" if e.end_date and e.end_date <= as_of else "starting"),
            "tenure_years": round(((as_of if active else (e.end_date or as_of)) - e.hire_date).days / metrics.DAYS_PER_YEAR, 1),
        }

    def search(self, query: str = "", department: str | None = None, site: str | None = None, contract: str | None = None,
               status: str = "active", page: int = 1) -> dict[str, Any]:
        as_of = self.repo.settings.as_of
        names = self.names()
        cards = [self._card(e, names, as_of)
                 for e in metrics.filter_employees(self.repo.employees(), department, site, contract)]
        if status in ("active", "left"):
            cards = [c for c in cards if c["status"] == status]
        needle = query.strip().lower()
        if needle:
            cards = [c for c in cards if needle in c["name"].lower() or needle in (c["email"] or "").lower()
                     or needle in c["employee_id"].lower() or needle in c["job_title"].lower()]
        cards.sort(key=lambda c: c["name"])
        start = (max(page, 1) - 1) * PAGE_SIZE
        return {"as_of": as_of.isoformat(), "total": len(cards), "page": max(page, 1), "page_size": PAGE_SIZE,
                "employees": cards[start:start + PAGE_SIZE], "synthetic": True}

    def record(self, employee_id: str) -> dict[str, Any]:
        as_of = self.repo.settings.as_of
        employees = self.repo.employees()
        person = next((e for e in employees if e.employee_id == employee_id), None)
        if person is None:
            raise NotFound(employee_id)
        names = self.names()
        card = self._card(person, names, as_of)
        manager = next((e for e in employees if e.employee_id == person.manager_id), None)
        reports = [e for e in employees if e.manager_id == employee_id and metrics.is_active(e, as_of)]
        courses = [r for r in self.repo.training() if r.employee_id == employee_id]
        return {
            "as_of": as_of.isoformat(), "synthetic": True, **card,
            "end_date": person.end_date.isoformat() if person.end_date else None,
            "exit_type": person.exit_type or None, "exit_reason": person.exit_reason or None,
            "manager": self._card(manager, names, as_of) if manager else None,
            "direct_reports": len(reports),
            "training": [{"course": r.course, "hours": r.hours, "completed": r.completed} for r in courses],
        }
