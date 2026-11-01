# Single LLM client wrapper used by all services: a local Ollama provider (stdlib only) and a fake for tests
import json
import logging
import os
import re
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
CONTEXT_WARNING_RATIO = 0.8


class LLMError(RuntimeError):
    """The model call failed (timeout, bad response...)."""


class LLMUnavailableError(LLMError):
    """Ollama is not running or the model is not installed; the message says how to fix it."""


class LLMConfigError(RuntimeError):
    pass


class LLMClient(Protocol):
    def generate(self, system: str, user: str, json_mode: bool = False) -> str: ...


def estimate_tokens(text: str) -> int:
    return len(text) // 4


class FakeLLM:
    """Scripted LLM for tests and offline runs: a queue of responses or a callable(system, user, json_mode)."""

    def __init__(self, responses: list[str] | Callable[[str, str, bool], str]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str, bool]] = []

    def generate(self, system: str, user: str, json_mode: bool = False) -> str:
        self.calls.append((system, user, json_mode))
        if callable(self._responses):
            return self._responses(system, user, json_mode)
        if not self._responses:
            raise LLMError("FakeLLM has no scripted response left")
        return self._responses.pop(0)


class OllamaLLM:
    """Native Ollama /api/chat client using only urllib. Prompts and answers are never logged."""

    def __init__(self, model: str, host: str = "http://localhost:11434", num_ctx: int = 8192,
                 timeout: float = 120.0, think: bool = False) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.num_ctx = num_ctx
        self.timeout = timeout
        self.think = think

    def generate(self, system: str, user: str, json_mode: bool = False) -> str:
        estimated = estimate_tokens(system) + estimate_tokens(user)
        if estimated > CONTEXT_WARNING_RATIO * self.num_ctx:
            logger.warning("LLM prompt is about %d tokens, over %d%% of LLM_NUM_CTX=%d; it may be truncated",
                           estimated, int(CONTEXT_WARNING_RATIO * 100), self.num_ctx)
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "think": self.think,  # reasoning models (e.g. Qwen3) answer ~10x faster without it
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
        }
        if json_mode:
            body["format"] = "json"
        request = urllib.request.Request(
            f"{self.host}/api/chat", data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise LLMUnavailableError(
                    f"Model '{self.model}' is not installed in Ollama. Run `ollama pull {self.model}`.") from None
            raise LLMError(f"Ollama returned HTTP {exc.code}") from None
        except (socket.timeout, TimeoutError):
            raise LLMError(f"Ollama did not answer within {self.timeout:.0f}s (LLM_TIMEOUT_SECONDS)") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise LLMError(f"Ollama did not answer within {self.timeout:.0f}s (LLM_TIMEOUT_SECONDS)") from None
            raise LLMUnavailableError(
                f"Ollama is not reachable at {self.host}. Start Ollama (the desktop app or `ollama serve`).") from None
        except (ValueError, OSError) as exc:
            raise LLMError(f"Unreadable response from Ollama ({type(exc).__name__})") from None
        content = (data.get("message") or {}).get("content")
        if not isinstance(content, str):
            raise LLMError("Ollama response has no message content")
        return THINK_BLOCK.sub("", content).strip()


def get_llm(provider: str | None = None, fake: LLMClient | None = None) -> LLMClient:
    """Client from LLM_PROVIDER (ollama | fake). `fake` is the offline client a service wants for 'fake'."""
    name = (provider or os.getenv("LLM_PROVIDER") or "fake").strip().lower()
    if name == "fake":
        if fake is None:
            raise LLMConfigError("LLM_PROVIDER=fake needs a service-provided fake client.")
        return fake
    if name == "ollama":
        model = os.getenv("LLM_MODEL", "").strip()
        if not model:
            raise LLMConfigError("LLM_MODEL is not set. Set it to an installed Ollama model, e.g. LLM_MODEL=qwen3.5:4b.")
        return OllamaLLM(
            model=model,
            host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            num_ctx=int(os.getenv("LLM_NUM_CTX") or 8192),
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS") or 120),
            think=os.getenv("LLM_THINK", "false").strip().lower() in ("1", "true", "yes"),
        )
    raise LLMConfigError(f"Unknown LLM_PROVIDER {name!r}; use ollama or fake.")
