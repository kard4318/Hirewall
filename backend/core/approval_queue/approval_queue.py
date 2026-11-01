# Queue of proposed actions awaiting human approval

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.paths import runtime_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    in_reply_to TEXT NOT NULL,
    proposal TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT
)
"""


class ApprovalError(Exception):
    """The requested change is not allowed for this item's current state."""


def payload_hash(to: str, subject: str, body: str, in_reply_to: str) -> str:
    """Hash exactly what would be sent, so an approval covers only this text."""
    payload = {"to": to, "subject": subject, "body": body, "in_reply_to": in_reply_to}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def proposal_hash(proposal: dict[str, Any]) -> str:
    return payload_hash(proposal["to"], proposal["subject"], proposal["body"], proposal["in_reply_to"])


@dataclass(frozen=True)
class ApprovalItem:
    id: str
    status: str
    thread_id: str
    in_reply_to: str
    proposal: dict[str, Any]
    payload_hash: str
    created_at: str
    decided_by: str | None
    decided_at: str | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _item(row: sqlite3.Row) -> ApprovalItem:
    values = dict(row)
    values["proposal"] = json.loads(values["proposal"])
    return ApprovalItem(**values)


class ApprovalQueue:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def submit(self, proposal: dict[str, Any], thread_id: str) -> ApprovalItem:
        """Add a proposal once, keyed by its idempotency key, replacing older pending drafts."""
        item_id = proposal["idempotency_key"]
        if proposal["payload_hash"] != proposal_hash(proposal):
            raise ApprovalError("hash_mismatch")
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO approvals"
                " (id, status, thread_id, in_reply_to, proposal, payload_hash, created_at)"
                " VALUES (?, 'pending', ?, ?, ?, ?, ?)",
                (item_id, thread_id, proposal["in_reply_to"], json.dumps(proposal), proposal["payload_hash"], _now()),
            )
            db.execute(
                "UPDATE approvals SET status = 'superseded' WHERE in_reply_to = ? AND id != ? AND status = 'pending'",
                (proposal["in_reply_to"], item_id),
            )
        return self.get(item_id)

    def get(self, item_id: str) -> ApprovalItem:
        with self._connect() as db:
            row = db.execute("SELECT * FROM approvals WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise ApprovalError("not_found")
        return _item(row)

    def list(self, status: str | None = None) -> list[ApprovalItem]:
        query, params = "SELECT * FROM approvals ORDER BY created_at", ()
        if status:
            query, params = "SELECT * FROM approvals WHERE status = ? ORDER BY created_at", (status,)
        with self._connect() as db:
            return [_item(row) for row in db.execute(query, params).fetchall()]

    def update_draft(self, item_id: str, proposal: dict[str, Any]) -> ApprovalItem:
        """Replace a pending draft with a recruiter's edit. Any earlier review no longer applies."""
        current = self.get(item_id)
        new_hash = proposal_hash(proposal)
        if proposal["payload_hash"] != new_hash:
            raise ApprovalError("hash_mismatch")
        if (proposal["to"], proposal["in_reply_to"]) != (current.proposal["to"], current.in_reply_to):
            raise ApprovalError("recipient_changed")
        with self._connect() as db:
            changed = db.execute(
                "UPDATE approvals SET proposal = ?, payload_hash = ? WHERE id = ? AND status = 'pending'",
                (json.dumps(proposal), new_hash, item_id),
            ).rowcount
        if changed != 1:
            raise ApprovalError("not_pending")
        return self.get(item_id)

    def approve(self, item_id: str, approver: str, expected_hash: str) -> ApprovalItem:
        """Record approval of the exact text the human reviewed."""
        if not approver.strip():
            raise ApprovalError("approver_required")
        self.get(item_id)
        with self._connect() as db:
            changed = db.execute(
                "UPDATE approvals SET status = 'approved', decided_by = ?, decided_at = ?"
                " WHERE id = ? AND status = 'pending' AND payload_hash = ?",
                (approver, _now(), item_id, expected_hash),
            ).rowcount
        if changed != 1:
            raise ApprovalError("not_pending_or_text_changed")
        return self.get(item_id)

    def reject(self, item_id: str, approver: str) -> ApprovalItem:
        if not approver.strip():
            raise ApprovalError("approver_required")
        self.get(item_id)
        with self._connect() as db:
            changed = db.execute(
                "UPDATE approvals SET status = 'rejected', decided_by = ?, decided_at = ?"
                " WHERE id = ? AND status = 'pending'",
                (approver, _now(), item_id),
            ).rowcount
        if changed != 1:
            raise ApprovalError("not_pending")
        return self.get(item_id)

    def claim_for_send(self, item_id: str) -> bool:
        """Atomically take an approved item, unless a reply to that email already went out."""
        with self._connect() as db:
            changed = db.execute(
                "UPDATE approvals SET status = 'sending' WHERE id = ? AND status = 'approved' AND NOT EXISTS ("
                " SELECT 1 FROM approvals AS other WHERE other.in_reply_to = approvals.in_reply_to"
                " AND other.id != approvals.id AND other.status IN ('sending', 'sent'))",
                (item_id,),
            ).rowcount
        return changed == 1

    def set_status(self, item_id: str, status: str, expected: str) -> None:
        with self._connect() as db:
            changed = db.execute(
                "UPDATE approvals SET status = ? WHERE id = ? AND status = ?", (status, item_id, expected)
            ).rowcount
        if changed != 1:
            raise ApprovalError("unexpected_status")


def get_approval_queue() -> ApprovalQueue:
    return ApprovalQueue(runtime_dir() / "approvals.sqlite3")
