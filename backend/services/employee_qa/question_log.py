# Anonymous log of employee questions for the People Team, with escalations; sensitive text is never stored
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.employee_qa.models import Answer

# Kinds whose question text is never kept: personal records, sensitive topics and blocked attempts.
WITHHELD_KINDS = {"sensitive", "refused_personal", "blocked"}
EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


class QuestionLog:
    def __init__(self, snapshot: Path | None = None, limit: int = 500) -> None:
        self._snapshot = snapshot
        self._limit = limit
        self._entries: list[dict[str, Any]] = []
        if snapshot and snapshot.is_file():
            self._entries = json.loads(snapshot.read_text(encoding="utf-8"))

    def add(self, question: str, answer: Answer, audience: str, now: datetime | None = None) -> str:
        entry_id = uuid.uuid4().hex[:12]
        withheld = answer.kind in WITHHELD_KINDS
        self._entries.append({
            "id": entry_id,
            "at": (now or datetime.now(timezone.utc)).isoformat(),
            "audience": audience,
            "kind": answer.kind,
            "topic": answer.topic,
            "mode": answer.mode,
            "citations": [c.section_id for c in answer.citations],
            "question": None if withheld else question.strip()[:500],
            "escalation": None,
        })
        del self._entries[: -self._limit]
        self._persist()
        return entry_id

    def escalate(self, entry_id: str, contact: str | None, now: datetime | None = None) -> dict[str, Any]:
        entry = self._find(entry_id)
        if contact is not None and not EMAIL.match(contact):
            raise ValueError("contact must be an email address")
        entry["escalation"] = {"at": (now or datetime.now(timezone.utc)).isoformat(), "contact": contact,
                               "status": "open"}
        self._persist()
        return entry

    def reply(self, entry_id: str, message: str, delivery: str, now: datetime | None = None) -> dict[str, Any]:
        """Record HR's reply on a hand-off and close it."""
        entry = self._find(entry_id)
        if not entry["escalation"]:
            raise KeyError(entry_id)
        entry["escalation"]["reply"] = {"message": message, "delivery": delivery,
                                        "at": (now or datetime.now(timezone.utc)).isoformat()}
        entry["escalation"]["status"] = "resolved"
        self._persist()
        return entry

    def get(self, entry_id: str) -> dict[str, Any]:
        return dict(self._find(entry_id))

    def resolve(self, entry_id: str) -> dict[str, Any]:
        entry = self._find(entry_id)
        if not entry["escalation"]:
            raise KeyError(entry_id)
        entry["escalation"]["status"] = "resolved"
        self._persist()
        return entry

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return [dict(e) for e in reversed(self._entries[-limit:])]

    def escalations(self) -> list[dict[str, Any]]:
        open_first = sorted((e for e in self._entries if e["escalation"]),
                            key=lambda e: (e["escalation"]["status"] != "open", e["escalation"]["at"]))
        return [dict(e) for e in open_first]

    def stats(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        topics: dict[str, int] = {}
        for e in self._entries:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
            if e["kind"] == "answered" and e["topic"]:
                topics[e["topic"]] = topics.get(e["topic"], 0) + 1
        open_count = sum(1 for e in self._entries if e["escalation"] and e["escalation"]["status"] == "open")
        return {"total": len(self._entries), "by_kind": kinds, "top_topics": sorted(topics.items(), key=lambda t: -t[1])[:5],
                "open_escalations": open_count}

    def _find(self, entry_id: str) -> dict[str, Any]:
        entry = next((e for e in self._entries if e["id"] == entry_id), None)
        if entry is None:
            raise KeyError(entry_id)
        return entry

    def _persist(self) -> None:
        if not self._snapshot:
            return
        self._snapshot.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._snapshot.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._entries, indent=1), encoding="utf-8")
        os.replace(tmp, self._snapshot)
