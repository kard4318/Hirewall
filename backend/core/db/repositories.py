# Data access repositories over the ORM models

import json
from pathlib import Path
from typing import Any

from core.paths import data_dir


class JsonCandidateDirectory:
    """Reads candidate records from a JSON file, until the database layer exists."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def find_by_email(self, email: str) -> list[dict[str, Any]]:
        records = json.loads(self._path.read_text(encoding="utf-8"))
        wanted = email.strip().lower()
        return [record for record in records if str(record.get("email", "")).strip().lower() == wanted]


def get_candidate_directory() -> JsonCandidateDirectory:
    return JsonCandidateDirectory(data_dir() / "candidate_status.json")
