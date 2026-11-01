# Pure people-analytics functions (definitions in README.md); no I/O, no individual-level outputs
from collections.abc import Iterable
from datetime import date, timedelta

from services.analytics.models import Employee, EngagementRow, TrainingRow

DAYS_PER_YEAR = 365.25


def filter_employees(employees: Iterable[Employee], department: str | None = None, site: str | None = None,
                     contract: str | None = None) -> list[Employee]:
    return [e for e in employees if (not department or e.department == department)
            and (not site or e.site == site) and (not contract or e.contract == contract)]


def is_active(e: Employee, day: date) -> bool:
    return e.hire_date <= day and (e.end_date is None or e.end_date > day)


def headcount(employees: Iterable[Employee], day: date) -> int:
    """Employees with hire_date <= day and (no end_date or end_date > day)."""
    return sum(1 for e in employees if is_active(e, day))


def hires(employees: Iterable[Employee], start: date, end: date) -> list[Employee]:
    return [e for e in employees if start <= e.hire_date <= end]


def exits(employees: Iterable[Employee], start: date, end: date) -> list[Employee]:
    return [e for e in employees if e.end_date is not None and start <= e.end_date <= end]


def average_headcount(employees: list[Employee], start: date, end: date) -> float:
    return (headcount(employees, start) + headcount(employees, end)) / 2


def attrition_rate(employees: list[Employee], start: date, end: date) -> float | None:
    """Exits in [start, end] divided by the average of the headcount on start and on end."""
    avg = average_headcount(employees, start, end)
    return len(exits(employees, start, end)) / avg if avg else None


def trailing_12m(day: date) -> tuple[date, date]:
    return day - timedelta(days=365), day


def attrition_rate_12m(employees: list[Employee], day: date) -> float | None:
    """Annualized figure for the KPI: attrition over the 365 days ending on `day`."""
    return attrition_rate(employees, *trailing_12m(day))


def avg_tenure_years(employees: Iterable[Employee], day: date) -> float | None:
    """Mean years from hire date to `day` over employees active on `day`."""
    spans = [(day - e.hire_date).days for e in employees if is_active(e, day)]
    return sum(spans) / len(spans) / DAYS_PER_YEAR if spans else None


def exit_tenure_years(e: Employee) -> float:
    return ((e.end_date or e.hire_date) - e.hire_date).days / DAYS_PER_YEAR


def voluntary_share(leavers: list[Employee]) -> float | None:
    """Voluntary exits divided by all exits."""
    return sum(e.exit_type == "voluntary" for e in leavers) / len(leavers) if leavers else None


def tenure_band(e: Employee, day: date) -> str:
    years = (day - e.hire_date).days / DAYS_PER_YEAR
    for limit, band in ((1, "<1y"), (2, "1-2y"), (3, "2-3y"), (5, "3-5y")):
        if years < limit:
            return band
    return "5y+"


# --- quarters ------------------------------------------------------------------------------------------

def quarter_label(day: date) -> str:
    return f"{day.year}Q{(day.month - 1) // 3 + 1}"


def quarter_bounds(label: str) -> tuple[date, date]:
    year, q = int(label[:4]), int(label[-1])
    start = date(year, 3 * q - 2, 1)
    end = (date(year + 1, 1, 1) if q == 4 else date(year, 3 * q + 1, 1)) - timedelta(days=1)
    return start, end


def quarters_between(start: date, end: date) -> list[str]:
    labels, current = [], quarter_label(start)
    while quarter_bounds(current)[0] <= end:
        labels.append(current)
        current = quarter_label(quarter_bounds(current)[1] + timedelta(days=1))
    return labels


def latest_complete_quarter(day: date) -> str:
    label = quarter_label(day)
    return label if quarter_bounds(label)[1] <= day else quarter_label(quarter_bounds(label)[0] - timedelta(days=1))


def previous_quarters(label: str, count: int) -> list[str]:
    """`count` quarters ending with `label`, oldest first."""
    labels = [label]
    while len(labels) < count:
        labels.insert(0, quarter_label(quarter_bounds(labels[0])[0] - timedelta(days=1)))
    return labels


def company_quarterly_average(employees: list[Employee], last_quarter: str, count: int = 8) -> float | None:
    """Mean of the company's quarterly attrition rates over the `count` quarters ending with `last_quarter`."""
    rates = [r for q in previous_quarters(last_quarter, count) if (r := attrition_rate(employees, *quarter_bounds(q))) is not None]
    return sum(rates) / len(rates) if rates else None


# --- engagement and training ---------------------------------------------------------------------------

def engagement_score(rows: Iterable[EngagementRow]) -> tuple[float | None, int]:
    """Respondent-weighted mean score and the number of respondents."""
    rows = list(rows)
    respondents = sum(r.respondents for r in rows)
    return (sum(r.score * r.respondents for r in rows) / respondents if respondents else None), respondents


def training_completion(rows: Iterable[TrainingRow]) -> tuple[float | None, float | None, int]:
    """(completed assignments / assignments, average hours per person, people)."""
    rows = list(rows)
    people = {r.employee_id for r in rows}
    if not rows:
        return None, None, 0
    return sum(r.completed for r in rows) / len(rows), sum(r.hours for r in rows) / len(people), len(people)


def delta(current: float | None, previous: float | None) -> float | None:
    return None if current is None or previous is None else current - previous
