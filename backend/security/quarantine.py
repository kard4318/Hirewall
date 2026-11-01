# Quarantines suspicious inputs for human review: one screen (rules + local model) used by every service
import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from security.injection_model import InjectionModel, load_injection_model
from security.pii_bias_filter import mask_pii
from security.rules import INVISIBLE, rule_hits

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]
Action = Literal["allow", "flag", "block"]
MODES = ("off", "monitor", "block")


@dataclass(frozen=True)
class Verdict:
    action: Action
    reasons: tuple[str, ...] = ()
    model_score: float | None = None
    source: str = ""

    @property
    def blocked(self) -> bool:
        return self.action == "block"


def _log_path() -> Path | None:
    """SECURITY_QUARANTINE_FILE; empty means memory only (tests)."""
    value = os.getenv("SECURITY_QUARANTINE_FILE", str(REPO_ROOT / "data" / "runtime" / "quarantine.jsonl"))
    return Path(value) if value.strip() else None


@dataclass
class SecuritySettings:
    """SECURITY_MODEL_MODE: off (rules only), monitor (model only flags), block (model can block)."""

    mode: str = field(default_factory=lambda: (os.getenv("SECURITY_MODEL_MODE") or "off").strip().lower())
    block_threshold: float = field(default_factory=lambda: float(os.getenv("SECURITY_MODEL_THRESHOLD") or 0.95))
    flag_threshold: float = field(default_factory=lambda: float(os.getenv("SECURITY_MODEL_FLAG_THRESHOLD") or 0.6))
    log_path: Path | None = field(default_factory=lambda: _log_path())

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"SECURITY_MODEL_MODE must be one of {MODES}")


class QuarantineLog:
    """Blocked and flagged inputs for human review: hash, masked excerpt and reasons (personal data masked)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.entries: list[dict] = []
        self._lock = threading.Lock()

    def record(self, text: str, verdict: Verdict) -> None:
        excerpt, _ = mask_pii(INVISIBLE.sub("", text)[:240])
        entry = {"at": datetime.now(timezone.utc).isoformat(), **asdict(verdict),
                 "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "excerpt": excerpt}
        with self._lock:
            self.entries.append(entry)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def mostly_latin(text: str) -> bool:
    """The classifier was trained on English; on other scripts (e.g. Arabic) it over-flags, so it may only flag there."""
    letters = [c for c in text if c.isalpha()]
    return not letters or sum(c.isascii() or "À" <= c <= "ɏ" for c in letters) / len(letters) >= 0.6


class SecurityScreen:
    def __init__(self, settings: SecuritySettings | None = None, model: InjectionModel | None | str = "auto",
                 log: QuarantineLog | None = None) -> None:
        self.settings = settings or SecuritySettings()
        self._model = model
        self.log = log or QuarantineLog(self.settings.log_path)

    def model(self) -> InjectionModel | None:
        if self.settings.mode == "off":
            return None
        if self._model == "auto":
            self._model = load_injection_model()
        return self._model  # type: ignore[return-value]

    def screen(self, text: str, source: str) -> Verdict:
        """Rules always run; the model adds a score. Rules block on their own; the model blocks only in block mode."""
        reasons = list(rule_hits(text))
        score = None
        model = self.model()
        if model is not None and text.strip():
            try:
                score = round(model.score(text), 4)
            except Exception as exc:  # noqa: BLE001 - a model failure must never let text bypass the rules
                logger.warning("injection model failed (%s); rules only", type(exc).__name__)
        if score is not None and score >= self.settings.flag_threshold:
            reasons.append(f"model:{score:.2f}")
        if any(r.startswith("rules:") for r in reasons):
            action: Action = "block"
        elif (score is not None and score >= self.settings.block_threshold and self.settings.mode == "block"
              and mostly_latin(text)):
            action = "block"
        elif score is not None and score >= self.settings.flag_threshold:
            action = "flag"
        else:
            action = "allow"
        verdict = Verdict(action, tuple(reasons), score, source)
        if action != "allow":
            self.log.record(text, verdict)
        return verdict


_default: SecurityScreen | None = None
_default_lock = threading.Lock()


def default_screen() -> SecurityScreen:
    global _default
    with _default_lock:
        if _default is None:
            _default = SecurityScreen()
        return _default


def screen_untrusted(text: str, source: str) -> Verdict:
    """The one call every service makes on untrusted text (candidate chat, emails, resumes, questions)."""
    return default_screen().screen(text, source)


def is_suspicious(text: str) -> bool:
    """Drop-in replacement for security.injection_detector.is_suspicious that also asks the model."""
    return screen_untrusted(text, "detector").blocked
