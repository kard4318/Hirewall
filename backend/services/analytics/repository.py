# Loads the synthetic people CSVs and the audit events (cached until the files change)
import csv
import json
from pathlib import Path
from typing import Any, Callable

from services.analytics.config import AnalyticsSettings
from services.analytics.models import AuditEvent, Employee, EngagementRow, OpenPosition, TrainingRow


class DataMissing(RuntimeError):
    """The people data has not been generated yet."""


class PeopleRepository:
    def __init__(self, settings: AnalyticsSettings) -> None:
        self.settings = settings
        self._cache: dict[Path, tuple[float, list[Any]]] = {}

    def _load(self, path: Path, parse: Callable[[Path], list[Any]]) -> list[Any]:
        if not path.is_file():
            raise DataMissing(f"{path.name} not found: run `python scripts/generate_people_data.py` first.")
        mtime = path.stat().st_mtime
        cached = self._cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        rows = parse(path)
        self._cache[path] = (mtime, rows)
        return rows

    @staticmethod
    def _csv(model: type) -> Callable[[Path], list[Any]]:
        def parse(path: Path) -> list[Any]:
            with path.open(encoding="utf-8", newline="") as handle:
                return [model.model_validate(row) for row in csv.DictReader(handle)]
        return parse

    def employees(self) -> list[Employee]:
        return self._load(self.settings.people_dir / "employees.csv", self._csv(Employee))

    def engagement(self) -> list[EngagementRow]:
        return self._load(self.settings.people_dir / "engagement.csv", self._csv(EngagementRow))

    def training(self) -> list[TrainingRow]:
        return self._load(self.settings.people_dir / "training.csv", self._csv(TrainingRow))

    def positions(self) -> list[OpenPosition]:
        return self._load(self.settings.people_dir / "open_positions.csv", self._csv(OpenPosition))

    def audit_events(self) -> list[AuditEvent]:
        """backend/core/audit has no reader yet, so the shared JSONL file is the source (see docs/audit-events.md)."""
        if not self.settings.audit_file.is_file():
            return []

        def parse(path: Path) -> list[AuditEvent]:
            lines = path.read_text(encoding="utf-8").splitlines()
            return [AuditEvent.model_validate(json.loads(line)) for line in lines if line.strip()]

        return self._load(self.settings.audit_file, parse)
