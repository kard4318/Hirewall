# Configuration for the employee_qa service
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_DIR = REPO_ROOT / "data" / "hr_documents"

# Calibrated on data/hr_documents/eval/questions.jsonl (see scripts/eval_knowledge.py --calibrate).
DEFAULT_BM25_MIN_SCORE = 4.5  # needed sections >= 5.31; off-topic <= 3.94 (q21 5.17 and q27 5.66 left to the LLM)


def _float(name: str, default: float) -> float:
    return float(os.getenv(name) or default)


def _int(name: str, default: int) -> int:
    return int(os.getenv(name) or default)


@dataclass(frozen=True)
class KnowledgeSettings:
    """Knobs of the knowledge assistant; tests build it directly."""

    docs_dir: Path = DOCS_DIR
    full_context_token_budget: int = field(default_factory=lambda: _int("FULL_CONTEXT_TOKEN_BUDGET", 3000))
    retrieval_top_k: int = field(default_factory=lambda: _int("RETRIEVAL_TOP_K", 5))
    bm25_min_score: float = field(default_factory=lambda: _float("BM25_MIN_SCORE", DEFAULT_BM25_MIN_SCORE))
    max_question_chars: int = 500
    max_answer_chars: int = 900
    max_answer_sentences: int = 5
