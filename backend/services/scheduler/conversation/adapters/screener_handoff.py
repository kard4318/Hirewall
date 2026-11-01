# Candidates a recruiter shortlisted in the screener, added to the mock results the scheduler reads
"""The real side of the ScreenerResults port. Records hold a name and an email because a human has approved
contacting this person, so they live in the runtime folder, which is never committed."""
import json
from pathlib import Path

from services.scheduler.conversation.adapters.screener_mock import MockScreenerResults
from services.scheduler.models import Job, PassedCandidate


class ScreenerHandoff:
    def __init__(self, path: Path, base: MockScreenerResults | None = None) -> None:
        self._path = path
        self._base = base or MockScreenerResults()
        self._jobs: dict[str, Job] = {}
        self._candidates: dict[str, PassedCandidate] = {}
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            self._jobs = {j["job_id"]: Job.model_validate(j) for j in data["jobs"]}
            self._candidates = {c["candidate_id"]: PassedCandidate.model_validate(c) for c in data["candidates"]}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"jobs": [j.model_dump(mode="json") for j in self._jobs.values()],
                "candidates": [c.model_dump(mode="json") for c in self._candidates.values()]}
        self._path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def add(self, job: Job, candidate: PassedCandidate) -> None:
        self._jobs[job.job_id] = job
        self._candidates[candidate.candidate_id] = candidate
        self._save()

    def remove(self, candidate_id: str) -> None:
        if self._candidates.pop(candidate_id, None) is not None:
            self._save()

    def list_jobs(self) -> list[Job]:
        known = {job.job_id for job in self._base.list_jobs()}
        return [*self._base.list_jobs(), *(job for job in self._jobs.values() if job.job_id not in known)]

    def list_passed(self, job_id: str) -> list[PassedCandidate]:
        added = [c for c in self._candidates.values() if c.job_id == job_id]
        return sorted([*self._base.list_passed(job_id), *added], key=lambda c: c.score, reverse=True)

    def find(self, candidate_id: str) -> PassedCandidate | None:
        return self._candidates.get(candidate_id) or self._base.find(candidate_id)
