# Single LLM client wrapper used by all services: structured JSON calls (ollama package) and plain-text
# calls (stdlib urllib) for the knowledge assistant, both local-only through Ollama

import json
import logging
import os
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from functools import cache
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
import ollama
from dotenv import load_dotenv

from core.llm.canary import leaked, new_canary, with_canary

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_HOST = "http://127.0.0.1:11434"
CONTEXT_TOKENS = 8192
MAX_OUTPUT_TOKENS = 2048
KEEP_ALIVE = "10m"
# Candidate data must stay on this machine, so other hosts are refused.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}


def is_local_url(url: str | None) -> bool:
    """True only for a model server on this machine. Candidate data must never reach a cloud model."""
    try:
        return bool(url) and urlsplit(url).hostname in _LOCAL_HOSTS
    except ValueError:
        return False


class LLMError(Exception):
    """A failed model call. Holds only a short code, never prompt or response text."""


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace $ref entries with their definitions, so small models get one flat grammar."""
    definitions = schema.get("$defs", {})

    def expand(node: Any, active: tuple[str, ...]) -> Any:
        if isinstance(node, list):
            return [expand(item, active) for item in node]
        if not isinstance(node, dict):
            return node
        reference = node.get("$ref")
        if reference is not None:
            name = reference.rsplit("/", 1)[-1]
            if name in active or name not in definitions:
                raise LLMError("unsupported_schema")
            siblings = {key: value for key, value in node.items() if key != "$ref"}
            return {**expand(definitions[name], (*active, name)), **expand(siblings, active)}
        return {key: expand(value, active) for key, value in node.items() if key != "$defs"}

    return expand(schema, ())


class LLMClient:
    """Makes single structured calls to a local model. It offers no tools and keeps no conversation."""

    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST, **client_options: Any) -> None:
        if urlsplit(host).hostname not in _LOCAL_HOSTS:
            raise LLMError("non_local_host")
        self._model = model
        self._host = host
        self._client_options = client_options

    def complete_json(
        self, *, system: str, user: str, json_schema: dict[str, Any], timeout_s: float
    ) -> str | Mapping[str, Any]:
        """Return the model's JSON text. A truncated prompt or response counts as a failure."""
        client = ollama.Client(host=self._host, timeout=timeout_s, **self._client_options)
        canary = new_canary()
        started = time.monotonic()
        try:
            response = client.chat(
                model=self._model,
                messages=[{"role": "system", "content": with_canary(system, canary)}, {"role": "user", "content": user}],
                format=_inline_refs(json_schema),
                think=False,
                stream=False,
                keep_alive=KEEP_ALIVE,
                options={"temperature": 0, "num_ctx": CONTEXT_TOKENS, "num_predict": MAX_OUTPUT_TOKENS},
            )
        except ollama.ResponseError as error:
            # Exception text can quote the request, so only the status code is kept.
            logger.warning("llm call failed status=%s", error.status_code)
            raise LLMError(f"status_{error.status_code}") from None
        except (ConnectionError, httpx.HTTPError, OSError) as error:
            logger.warning("llm call failed error_type=%s", type(error).__name__)
            raise LLMError(type(error).__name__) from None

        logger.info(
            "llm call model=%s done_reason=%s input_tokens=%s output_tokens=%s latency_ms=%s",
            self._model,
            response.done_reason,
            response.prompt_eval_count,
            response.eval_count,
            round((time.monotonic() - started) * 1000),
        )
        # Ollama silently drops prompt text that does not fit the context, which could remove the email or rules.
        if (response.prompt_eval_count or 0) >= CONTEXT_TOKENS:
            raise LLMError("context_exceeded")
        if response.done_reason != "stop":
            raise LLMError(str(response.done_reason or "no_done_reason"))
        text = response.message.content
        if not text:
            raise LLMError("no_text_output")
        if leaked(text, canary):
            logger.warning("llm output dropped reason=canary_leak")
            raise LLMError("canary_leak")
        return text


@cache
def get_llm_client() -> LLMClient:
    """Build the shared client from LLM_MODEL and LLM_HOST, reading .env if present."""
    load_dotenv()
    return LLMClient(os.getenv("LLM_MODEL") or DEFAULT_MODEL, os.getenv("LLM_HOST") or DEFAULT_HOST)


# --- Plain-text clients used by the knowledge assistant (stdlib only) ---------------------------------------
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
CONTEXT_WARNING_RATIO = 0.8


class LLMUnavailableError(LLMError):
    """Ollama is not running or the model is not installed; the message says how to fix it."""


class LLMConfigError(RuntimeError):
    pass


class TextLLM(Protocol):
    """Plain-text client used by the knowledge assistant (generate -> text)."""

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
        canary = new_canary()
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": with_canary(system, canary)}, {"role": "user", "content": user}],
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
        if leaked(content, canary):
            logger.warning("llm output dropped reason=canary_leak")
            raise LLMError("canary_leak")
        return THINK_BLOCK.sub("", content).strip()


def get_llm(provider: str | None = None, fake: TextLLM | None = None) -> TextLLM:
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
