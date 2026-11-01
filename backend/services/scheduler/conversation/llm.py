# LLM client port, fake and real adapters, and strict structured-output helper for the scheduler
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from core.llm.client import is_local_url

T = TypeVar("T", bound=BaseModel)

def request_timeout() -> float:
    """Seconds per LLM request from LLM_TIMEOUT (raise it for slow local models)."""
    return float(os.getenv("LLM_TIMEOUT") or 30)

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LLMError(RuntimeError):
    pass


class LLMConfigError(RuntimeError):
    pass


class StructuredOutputError(RuntimeError):
    pass


class LLMClient(Protocol):
    def generate(self, system: str, user: str) -> str: ...


class FakeLLM:
    """Scripted LLM: a queue of responses or a callable(system, user) -> str."""

    def __init__(self, responses: list[str] | Callable[[str, str], str]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if callable(self._responses):
            return self._responses(system, user)
        if not self._responses:
            raise LLMError("FakeLLM has no scripted response left")
        return self._responses.pop(0)


class OpenAILLM:
    """An OpenAI-compatible server on this machine (LLM_BASE_URL), e.g. Ollama at http://localhost:11434/v1."""

    def __init__(self, api_key: str, model: str, base_url: str | None) -> None:
        import openai  # optional dependency, imported only when selected

        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=request_timeout())
        self._model = model
        # Optional, e.g. "none" turns off Qwen3 thinking on Ollama (~8s -> <1s per call).
        effort = os.getenv("LLM_REASONING_EFFORT", "").strip()
        self._extra = {"reasoning_effort": effort} if effort else {}

    def generate(self, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            response_format={"type": "json_object"},  # every caller expects one JSON object
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            extra_body=self._extra or None,
        )
        # Reasoning models (e.g. Qwen3) may prepend <think>...</think>; only the answer is parsed.
        return THINK_BLOCK.sub("", response.choices[0].message.content or "").strip()


def get_llm(provider: str | None = None) -> LLMClient:
    """Builds the client named by `provider` or LLM_PROVIDER (fake | openai). Only local model servers are allowed."""
    name = (provider or os.getenv("LLM_PROVIDER") or "fake").strip().lower()
    if name == "fake":
        from services.scheduler.conversation.demo_llm import demo_rules

        return FakeLLM(demo_rules)
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "")
    if not api_key:
        raise LLMConfigError(f"LLM_PROVIDER={name} needs LLM_API_KEY in .env.")
    if name == "anthropic":
        raise LLMConfigError("Cloud models are not allowed: candidate data stays on this machine. Use LLM_PROVIDER=openai "
                             "with a local LLM_BASE_URL such as http://localhost:11434/v1.")
    if name == "openai":
        if not model:
            raise LLMConfigError("LLM_PROVIDER=openai needs LLM_MODEL in .env.")
        base_url = os.getenv("LLM_BASE_URL", "").strip()
        if not is_local_url(base_url):
            raise LLMConfigError("LLM_BASE_URL must point to a model server on this machine, e.g. "
                                 "http://localhost:11434/v1. Cloud APIs are not allowed.")
        return OpenAILLM(api_key, model, base_url)
    raise LLMConfigError(f"Unknown LLM_PROVIDER {name!r}; use fake or openai.")


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def wrap_untrusted(text: str) -> str:
    """Candidate text as data: angle brackets escaped so it cannot close or fake the tags."""
    escaped = text.replace("<", "&lt;").replace(">", "&gt;")
    return f"<candidate_message>\n{escaped}\n</candidate_message>"


def extract_json(text: str) -> dict[str, Any]:
    """First JSON object in the text (tolerates code fences or chatter around it)."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    raise ValueError("no JSON object found in the model output")


def structured(
    llm: LLMClient, system: str, user: str, schema: type[T], context: dict[str, Any] | None = None
) -> T:
    """Validated model output; one retry with the validation error, then StructuredOutputError."""
    system_full = (
        f"{system}\n\nReturn only one JSON object matching this JSON schema:\n"
        f"{json.dumps(schema.model_json_schema(), separators=(',', ':'))}"
    )
    prompt = user
    error = "no attempt made"
    for _ in range(2):
        try:
            text = llm.generate(system_full, prompt)
        except Exception as exc:  # noqa: BLE001 - any client failure becomes a retry, then a fallback
            error = f"LLM call failed ({type(exc).__name__})"
            continue
        try:
            return schema.model_validate(extract_json(text), context=context)
        except (ValueError, ValidationError) as exc:
            error = str(exc)[:500]
            prompt = f"{user}\n\nYour previous output was invalid: {error}\nReturn only a corrected JSON object."
    raise StructuredOutputError(error)
