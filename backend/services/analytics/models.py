# Pydantic models for the people-analytics inputs (synthetic CSVs and the shared audit-event contract)
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class Employee(BaseModel):
    """Pseudonymous employee record. Only age band and gender as demographics; never names."""

    model_config = ConfigDict(frozen=True)
    employee_id: str
    department: str
    job_title: str
    level: str
    site: str
    contract: Literal["permanent", "fixed_term", "intern"]
    hire_date: date
    end_date: date | None = None
    exit_type: str = ""
    exit_reason: str = ""
    age_band: str
    gender: str
    manager_id: str = ""

    @field_validator("end_date", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if value in ("", None) else value


class EngagementRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    quarter: str          # "2026Q2"
    department: str
    site: str
    score: float          # 1-5
    response_rate: float
    respondents: int


class TrainingRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    employee_id: str
    course: str
    hours: float
    completed: bool


class OpenPosition(BaseModel):
    model_config = ConfigDict(frozen=True)
    job_id: str
    department: str
    title: str
    opened_date: date
    status: str


class AuditEvent(BaseModel):
    """docs/audit-events.md. Unknown extra fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    ts: datetime
    event: str
    actor: str = "agent"
    reason_code: str = ""
    job_id: str | None = None
    candidate_ref: str | None = None
    outcome: str | None = None
    topic: str | None = None
    synthetic: bool = False
