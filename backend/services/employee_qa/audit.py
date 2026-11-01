# Audit port and in-memory adapter for the knowledge assistant (ids and codes only, never question or answer text)
from typing import Any, Protocol


class AuditLog(Protocol):
    def record(self, event: str, **fields: Any) -> None: ...


class MemoryAuditLog:
    ALLOWED = {"kind", "topic", "mode", "section_ids", "audience", "reason", "latency_ms", "prompt_tokens"}

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, event: str, **fields: Any) -> None:
        unknown = set(fields) - self.ALLOWED
        if unknown:  # guard against someone passing free text by accident
            raise ValueError(f"audit fields not allowed: {sorted(unknown)}")
        self.entries.append({"event": event, **fields})
