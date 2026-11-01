# Helpers for schema-validated structured LLM output: extract JSON, validate, one retry with the error
import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from core.llm.client import LLMClient

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """The model did not return valid JSON for the schema, even after one retry."""


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


def structured(llm: LLMClient, system: str, user: str, schema: type[T]) -> T:
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
