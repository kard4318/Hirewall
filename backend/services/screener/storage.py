# SQLite storage for the screener: candidates, tasks, jobs, runs, proposals; identity in its own file
"""All records are JSON documents keyed by id. Identity is kept in a separate file,
so everything the scoring code can open is pseudonymous."""
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.paths import runtime_dir
from services.screener.models import IdentityRecord, IngestionTask, JobOffer, ScreeningRun, StoredCandidate

_TABLES = ("tasks", "jobs", "runs", "proposals", "rubric_cache")


class _Database:
    def __init__(self, path: Path, schema: list[str]) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            for statement in schema:
                db.execute(statement)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()


class ScreenerStore:
    def __init__(self, path: Path | None = None) -> None:
        schema = [
            "CREATE TABLE IF NOT EXISTS candidates (candidate_id TEXT PRIMARY KEY, content_hash TEXT UNIQUE NOT NULL,"
            " data TEXT NOT NULL)",
            *(f"CREATE TABLE IF NOT EXISTS {t} (id TEXT PRIMARY KEY, data TEXT NOT NULL)" for t in _TABLES),
        ]
        self._db = _Database(path or runtime_dir() / "screener.sqlite3", schema)

    def _put(self, table: str, item_id: str, data: str) -> None:
        with self._db.connect() as db:
            db.execute(f"INSERT OR REPLACE INTO {table} (id, data) VALUES (?, ?)", (item_id, data))

    def _get(self, table: str, item_id: str) -> str | None:
        with self._db.connect() as db:
            row = db.execute(f"SELECT data FROM {table} WHERE id = ?", (item_id,)).fetchone()
        return row["data"] if row else None

    def add_candidate(self, candidate: StoredCandidate) -> None:
        with self._db.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO candidates (candidate_id, content_hash, data) VALUES (?, ?, ?)",
                (candidate.candidate_id, candidate.content_hash, candidate.model_dump_json()),
            )

    def candidate_by_hash(self, content_hash: str) -> StoredCandidate | None:
        with self._db.connect() as db:
            row = db.execute("SELECT data FROM candidates WHERE content_hash = ?", (content_hash,)).fetchone()
        return StoredCandidate.model_validate_json(row["data"]) if row else None

    def get_candidate(self, candidate_id: str) -> StoredCandidate | None:
        with self._db.connect() as db:
            row = db.execute("SELECT data FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        return StoredCandidate.model_validate_json(row["data"]) if row else None

    def list_candidates(self) -> list[StoredCandidate]:
        with self._db.connect() as db:
            rows = db.execute("SELECT data FROM candidates ORDER BY candidate_id").fetchall()
        return [StoredCandidate.model_validate_json(row["data"]) for row in rows]

    def save_task(self, task: IngestionTask) -> None:
        self._put("tasks", task.task_id, task.model_dump_json())

    def get_task(self, task_id: str) -> IngestionTask | None:
        data = self._get("tasks", task_id)
        return IngestionTask.model_validate_json(data) if data else None

    def save_job(self, job: JobOffer) -> None:
        self._put("jobs", job.job_id, job.model_dump_json())

    def list_jobs(self) -> list[JobOffer]:
        with self._db.connect() as db:
            rows = db.execute("SELECT data FROM jobs ORDER BY id").fetchall()
        return [JobOffer.model_validate_json(row["data"]) for row in rows]

    def save_run(self, run: ScreeningRun) -> None:
        self._put("runs", run.run_id, run.model_dump_json())

    def get_run(self, run_id: str) -> ScreeningRun | None:
        data = self._get("runs", run_id)
        return ScreeningRun.model_validate_json(data) if data else None

    def save_proposal(self, proposal_id: str, proposal: dict[str, Any]) -> None:
        self._put("proposals", proposal_id, json.dumps(proposal))

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        data = self._get("proposals", proposal_id)
        return json.loads(data) if data else None

    def cache_rubric(self, key: str, data: str) -> None:
        self._put("rubric_cache", key, data)

    def cached_rubric(self, key: str) -> str | None:
        return self._get("rubric_cache", key)


class IdentityStore:
    """Who candidates are. Only ScreeningService.reveal_identity reads it, and that call is audited."""

    def __init__(self, path: Path | None = None) -> None:
        schema = ["CREATE TABLE IF NOT EXISTS identity (candidate_id TEXT PRIMARY KEY, data TEXT NOT NULL)"]
        self._db = _Database(path or runtime_dir() / "screener_identity.sqlite3", schema)

    def save(self, record: IdentityRecord) -> None:
        with self._db.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO identity (candidate_id, data) VALUES (?, ?)",
                (record.candidate_id, record.model_dump_json()),
            )

    def get(self, candidate_id: str) -> IdentityRecord | None:
        with self._db.connect() as db:
            row = db.execute("SELECT data FROM identity WHERE candidate_id = ?", (candidate_id,)).fetchone()
        return IdentityRecord.model_validate_json(row["data"]) if row else None
