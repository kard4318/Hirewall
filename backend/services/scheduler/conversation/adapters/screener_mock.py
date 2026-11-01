# Mock screener results from data/screener_mock/, and the candidate repo the scheduler reads from them
import json
from pathlib import Path
from typing import Any

from services.scheduler.config import REPO_ROOT
from services.scheduler.models import Job, PassedCandidate
from services.scheduler.scheduling_state import SchedulingStateStore

DEFAULT_DIR = REPO_ROOT / "data" / "screener_mock"
# Statuses where HR has invited the candidate, so their booking link may be used.
INVITED_STATUSES = {"invited", "pending_approval", "booked"}


class MockScreenerResults:
    """Implements the ScreenerResults port until the real screener service hands results over."""

    def __init__(self, data_dir: Path = DEFAULT_DIR) -> None:
        self._jobs = [Job.model_validate(j) for j in json.loads((data_dir / "jobs.json").read_text(encoding="utf-8"))]
        self._candidates = [PassedCandidate.model_validate(c)
                            for c in json.loads((data_dir / "candidates.json").read_text(encoding="utf-8"))]

    def list_jobs(self) -> list[Job]:
        return list(self._jobs)

    def list_passed(self, job_id: str) -> list[PassedCandidate]:
        return sorted((c for c in self._candidates if c.job_id == job_id), key=lambda c: c.score, reverse=True)

    def find(self, candidate_id: str) -> PassedCandidate | None:
        return next((c for c in self._candidates if c.candidate_id == candidate_id), None)


class ScreenerCandidateRepo:
    """CandidateRepo port over the screener data: a link only works once HR has invited the candidate."""

    def __init__(self, screener: MockScreenerResults, state: SchedulingStateStore) -> None:
        self._screener = screener
        self._state = state

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        record = self._screener.find(candidate_id)
        if record is None:
            return None
        invited = self._state.status(candidate_id) in INVITED_STATUSES
        return {
            "first_name": record.first_name,
            "last_name": record.last_name,
            "email": record.email,
            "job_id": record.job_id,
            "job_title": record.job_title,
            "status": "approved_for_interview" if invited else "passed",
        }
