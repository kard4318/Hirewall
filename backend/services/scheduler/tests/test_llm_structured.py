# Tests for the structured-output helper and LLM factory (no network)
from typing import Literal

import pytest
from pydantic import BaseModel

from services.scheduler.conversation.llm import (
    FakeLLM,
    LLMConfigError,
    StructuredOutputError,
    extract_json,
    get_llm,
    structured,
)


class Pick(BaseModel):
    intent: Literal["yes", "no"]


def test_extract_json_ignores_chatter_and_fences() -> None:
    assert extract_json('Sure!\n```json\n{"intent": "yes"}\n```') == {"intent": "yes"}


def test_invalid_then_valid_json_succeeds_with_error_fed_back() -> None:
    llm = FakeLLM(["not json at all", '{"intent": "yes"}'])
    assert structured(llm, "sys", "user", Pick).intent == "yes"
    assert len(llm.calls) == 2
    assert "previous output was invalid" in llm.calls[1][1]


def test_schema_violation_then_valid_succeeds() -> None:
    llm = FakeLLM(['{"intent": "maybe"}', '{"intent": "no"}'])
    assert structured(llm, "sys", "user", Pick).intent == "no"


def test_invalid_twice_raises() -> None:
    with pytest.raises(StructuredOutputError):
        structured(FakeLLM(["nope", "{still bad"]), "sys", "user", Pick)


def test_client_exceptions_become_structured_error() -> None:
    def boom(system: str, user: str) -> str:
        raise TimeoutError("slow")

    with pytest.raises(StructuredOutputError):
        structured(FakeLLM(boom), "sys", "user", Pick)


def test_schema_is_appended_to_system_prompt() -> None:
    llm = FakeLLM(['{"intent": "yes"}'])
    structured(llm, "base system", "user", Pick)
    assert llm.calls[0][0].startswith("base system") and '"intent"' in llm.calls[0][0]


def test_factory_defaults_to_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(get_llm(), FakeLLM)


def test_real_provider_without_key_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(LLMConfigError, match="LLM_API_KEY"):
        get_llm("anthropic")


def test_unknown_provider_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "x")
    with pytest.raises(LLMConfigError):
        get_llm("mystery")
