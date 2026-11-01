# Local prompt-injection classifier (DeBERTa-v3, ONNX via onnxruntime): a second opinion next to the rules
import json
import logging
import os
import threading
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "models" / "prompt-injection-v2"  # scripts/download_security_models.py
MAX_TOKENS = 512
WINDOW_STRIDE = 384  # overlapping windows, so long texts (resumes, emails) are fully covered


class InjectionModel(Protocol):
    def score(self, text: str) -> float:
        """Probability (0..1) that the text is a prompt injection."""
        ...


class StaticModel:
    """Fixed or rule-driven scores for tests and offline runs."""

    def __init__(self, score: float | dict[str, float] = 0.0) -> None:
        self._score = score
        self.calls: list[str] = []

    def score(self, text: str) -> float:
        self.calls.append(text)
        if isinstance(self._score, dict):
            return max((s for needle, s in self._score.items() if needle in text), default=0.0)
        return float(self._score)


class OnnxInjectionModel:
    """protectai/deberta-v3-base-prompt-injection-v2 exported to ONNX. Runs on CPU, fully offline."""

    def __init__(self, model_dir: Path) -> None:
        import numpy as np
        import onnxruntime
        from tokenizers import Tokenizer

        self._np = np
        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        options = onnxruntime.SessionOptions()
        options.log_severity_level = 3
        self._session = onnxruntime.InferenceSession(str(model_dir / "model.onnx"), options,
                                                     providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}
        labels = json.loads((model_dir / "config.json").read_text(encoding="utf-8")).get("id2label", {})
        self._injection_index = next((int(i) for i, name in labels.items() if name.upper() == "INJECTION"), 1)
        self._lock = threading.Lock()

    def score(self, text: str) -> float:
        np = self._np
        ids = self._tokenizer.encode(text).ids
        if len(ids) <= MAX_TOKENS:
            windows = [ids]
        else:  # keep [CLS] .. [SEP] framing per window
            body, cls, sep = ids[1:-1], ids[0], ids[-1]
            size = MAX_TOKENS - 2
            windows = [[cls, *body[i:i + size], sep] for i in range(0, max(len(body) - size, 0) + WINDOW_STRIDE, WINDOW_STRIDE)
                       if body[i:i + size]]
        best = 0.0
        with self._lock:
            for window in windows:
                feed = {"input_ids": np.array([window], dtype=np.int64),
                        "attention_mask": np.ones((1, len(window)), dtype=np.int64)}
                if "token_type_ids" in self._inputs:
                    feed["token_type_ids"] = np.zeros((1, len(window)), dtype=np.int64)
                logits = self._session.run(None, {k: v for k, v in feed.items() if k in self._inputs})[0][0]
                exp = np.exp(logits - logits.max())
                best = max(best, float(exp[self._injection_index] / exp.sum()))
        return best


_loaded: dict[str, InjectionModel | None] = {}
_load_lock = threading.Lock()


def load_injection_model() -> InjectionModel | None:
    """The configured model, loaded once; None (rules only) when the files are not downloaded."""
    model_dir = Path(os.getenv("SECURITY_MODEL_DIR") or DEFAULT_DIR)
    key = str(model_dir)
    with _load_lock:
        if key not in _loaded:
            if (model_dir / "model.onnx").is_file() and (model_dir / "tokenizer.json").is_file():
                _loaded[key] = OnnxInjectionModel(model_dir)
            else:
                logger.warning("injection model not found in %s; rules only (run scripts/download_security_models.py)",
                               model_dir)
                _loaded[key] = None
        return _loaded[key]
