"""Offline fakes for the screener: a model that needs no Ollama, and a service wired to temp files."""
import json
import re
from pathlib import Path
from typing import Any

from core.audit.audit_log import AuditLog
from core.candidate_status.store import CandidateStatusStore
from core.llm.embeddings import HashingEmbedder
from services.screener.config import RankingWeights, SemanticConfig
from services.screener.service import ScreeningService
from services.screener.storage import IdentityStore, ScreenerStore

REPO_ROOT = Path(__file__).resolve().parents[4]
ATTACK_PDF = REPO_ROOT / "data/resumes/cvs/attack_hidden_text.pdf"


class FakeLLM:
    """Answers extraction and rubric calls. A rubric answer can depend on what the prompt contains."""

    def __init__(self, rubric: tuple[int, int, int] = (6, 6, 6), extraction_fails: bool = False) -> None:
        self.rubric = rubric
        self.extraction_fails = extraction_fails
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if "skills_coverage" in kwargs["json_schema"]["properties"]:
            a, b, c = self.rubric
            return {"skills_text": "Lists the skills.", "skills_coverage": a, "experience_text": "Some work.",
                    "related_experience": b, "field_text": "Close field.", "field_closeness": c}
        if self.extraction_fails:
            return "not json"
        fence = re.search(r"BEGIN_\S+\n(.*)\nEND_", kwargs["user"], re.S).group(1)
        return json.dumps({"sections": [{"kind": "experience", "text": fence}],
                           "profile": {"current_title": "Developer", "skills": ["Python"]}})

    def prompts(self) -> str:
        return "\n".join(call["system"] + call["user"] for call in self.calls)


def make_service(tmp_path: Path, llm: Any = None, *, background: bool = False, **kwargs: Any) -> ScreeningService:
    kwargs.setdefault("weights", RankingWeights(semantic=0.35, rubric=0.45, experience=0.2, graph=0.0))
    return ScreeningService(
        store=ScreenerStore(tmp_path / "screener.sqlite3"),
        identity=IdentityStore(tmp_path / "identity.sqlite3"),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        status_store=CandidateStatusStore(tmp_path / "status.sqlite3"),
        llm=llm,
        embedder=HashingEmbedder(),
        semantic_config=SemanticConfig(floor=0.0, ceiling=0.6),
        background=background,
        **kwargs,
    )
