# Helpers for schema-validated structured LLM output

from collections.abc import Mapping
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .client import LLMClient

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
