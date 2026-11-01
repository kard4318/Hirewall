# Append-only audit log of agent and human actions

import hashlib
import json
import threading
from datetime import datetime, timezone

UTC = timezone.utc  # datetime.UTC needs Python 3.11+
from pathlib import Path
from typing import Any

from core.paths import runtime_dir

_GENESIS = "0" * 64
_WRITE_LOCK = threading.Lock()


def _entry_hash(entry: dict[str, Any]) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLog:
    """A JSON Lines file where each entry includes the hash of the one before it."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _last_hash(self) -> str:
        if not self._path.exists():
            return _GENESIS
        last = _GENESIS
        with self._path.open(encoding="utf-8") as lines:
            for line in lines:
                if line.strip():
                    last = json.loads(line)["hash"]
        return last

    def record(self, event: str, **fields: Any) -> None:
        """Append one event. Callers must pass IDs and outcomes, not email or draft text."""
        with _WRITE_LOCK:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "at": datetime.now(UTC).isoformat(),
                "event": event,
                "fields": fields,
                "previous_hash": self._last_hash(),
            }
            entry["hash"] = _entry_hash(entry)
            with self._path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def verify(self) -> bool:
        """Return False if any entry was changed, removed, or reordered."""
        previous = _GENESIS
        for entry in self.entries():
            body = {key: value for key, value in entry.items() if key != "hash"}
            if entry["previous_hash"] != previous or _entry_hash(body) != entry["hash"]:
                return False
            previous = entry["hash"]
        return True


def get_audit_sink() -> AuditLog:
    return AuditLog(runtime_dir() / "audit.jsonl")
