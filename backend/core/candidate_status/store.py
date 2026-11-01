# Candidate decisions recorded by the executor after human approval
"""Only core/executor writes here. Services read it to show a candidate's current status."""
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from core.paths import runtime_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate_status (
    job_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    status TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (job_id, candidate_id, approval_id)
)
"""


class CandidateStatusStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record(self, job_id: str, candidate_ids: list[str], status: str, approval_id: str) -> None:
        """Write one approved decision. Repeating the same approval changes nothing."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.executemany(
                "INSERT OR IGNORE INTO candidate_status (job_id, candidate_id, status, approval_id, recorded_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [(job_id, candidate_id, status, approval_id, now) for candidate_id in candidate_ids],
            )

    def statuses_for(self, job_id: str) -> dict[str, str]:
        """The latest recorded status of each candidate for this job."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT candidate_id, status FROM candidate_status WHERE job_id = ? ORDER BY recorded_at, rowid",
                (job_id,),
            ).fetchall()
        return {row["candidate_id"]: row["status"] for row in rows}


    def history_for(self, candidate_id: str) -> list[tuple[str, str, str]]:
        """(job_id, status, recorded_at) for one candidate, oldest first."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT job_id, status, recorded_at FROM candidate_status WHERE candidate_id = ? ORDER BY recorded_at, rowid",
                (candidate_id,),
            ).fetchall()
        return [(row["job_id"], row["status"], row["recorded_at"]) for row in rows]

    def erase(self, candidate_id: str) -> int:
        with self._connect() as db:
            return db.execute("DELETE FROM candidate_status WHERE candidate_id = ?", (candidate_id,)).rowcount


def get_candidate_status_store() -> CandidateStatusStore:
    return CandidateStatusStore(runtime_dir() / "candidate_status.sqlite3")
