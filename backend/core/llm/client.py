# Single LLM client wrapper used by all services

import logging
import os
import time
from collections.abc import Mapping
from functools import cache
from typing import Any
from urllib.parse import urlsplit

import httpx
import ollama
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_HOST = "http://127.0.0.1:11434"
CONTEXT_TOKENS = 8192
MAX_OUTPUT_TOKENS = 2048
KEEP_ALIVE = "10m"
# Candidate data must stay on this machine, so other hosts are refused.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}


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
        started = time.monotonic()
        try:
            response = client.chat(
                model=self._model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
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
        return text


@cache
def get_llm_client() -> LLMClient:
    """Build the shared client from LLM_MODEL and LLM_HOST, reading .env if present."""
    load_dotenv()
    return LLMClient(os.getenv("LLM_MODEL") or DEFAULT_MODEL, os.getenv("LLM_HOST") or DEFAULT_HOST)
