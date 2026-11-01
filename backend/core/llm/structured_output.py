# Helpers for schema-validated structured LLM output: generate_structured (JSON-schema calls) and
# structured (plain-text calls with JSON extraction), both with one repair attempt

import json
from collections.abc import Mapping
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .client import LLMClient, TextLLM

Model = TypeVar("Model", bound=BaseModel)

_REPAIR_INSTRUCTION = "\n\nYour previous response did not match the required JSON schema. Return only valid JSON."


class StructuredOutputError(Exception):
    """The model kept returning invalid output. Holds no prompt or response text."""


def generate_structured(client: LLMClient, schema: type[Model], *, system: str, user: str, timeout_s: float) -> Model:
    """Call the model and validate the result, allowing one repair attempt."""
    json_schema = schema.model_json_schema()
    for prompt in (user, user + _REPAIR_INSTRUCTION):
        raw = client.complete_json(system=system, user=prompt, json_schema=json_schema, timeout_s=timeout_s)
        try:
            if isinstance(raw, Mapping):
                return schema.model_validate(raw)
            return schema.model_validate_json(raw)
        except (ValidationError, ValueError):
            continue
    raise StructuredOutputError("invalid_output")


T = TypeVar("T", bound=BaseModel)


def extract_json(text: str) -> dict[str, Any]:
    """First JSON object in the text; tolerates code fences or chatter around it."""
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


def structured(llm: TextLLM, system: str, user: str, schema: type[T]) -> T:
    """Validated output. Connection or model errors propagate at once (retrying cannot fix them)."""
    system_full = (f"{system}\n\nReply with one JSON object only, matching this JSON schema:\n"
                   f"{json.dumps(schema.model_json_schema(), separators=(',', ':'))}")
    prompt = user
    error = ""
    for _ in range(2):
        text = llm.generate(system_full, prompt, json_mode=True)
        try:
            return schema.model_validate(extract_json(text))
        except (ValueError, ValidationError) as exc:
            error = str(exc)[:400]
            prompt = f"{user}\n\nYour previous output was invalid: {error}\nReply with a corrected JSON object only."
    raise StructuredOutputError(error)
