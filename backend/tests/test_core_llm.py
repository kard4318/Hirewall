# Runs the real Ollama client against a mock HTTP transport, so no server or model is needed

import json
import logging

import httpx
import pytest
from pydantic import BaseModel

from core.llm.client import (
    CONTEXT_TOKENS,
    DEFAULT_HOST,
    DEFAULT_MODEL,
    MAX_OUTPUT_TOKENS,
    LLMClient,
    LLMError,
    _inline_refs,
    get_llm_client,
)
from core.llm.structured_output import StructuredOutputError, generate_structured
from services.drafter.models import LLMDraft
from services.drafter.node import _run
from services.drafter.tests.helpers import SENDER, draft_json, make_deps, make_request

SCHEMA = LLMDraft.model_json_schema()
PROMPT_MARKER = "PROMPT-TEXT-MARKER"


def chat_response(text: str = "{}", done_reason: str = "stop", prompt_tokens: int = 10) -> dict:
    return {
        "model": DEFAULT_MODEL,
        "created_at": "2026-11-01T00:00:00Z",
        "message": {"role": "assistant", "content": text},
        "done": True,
        "done_reason": done_reason,
        "prompt_eval_count": prompt_tokens,
        "eval_count": 5,
    }


class Server:
    """Replays scripted responses and records each request."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses[min(len(self.requests), len(self.responses)) - 1]

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


def ok(text: str = "{}", done_reason: str = "stop", prompt_tokens: int = 10) -> httpx.Response:
    return httpx.Response(200, json=chat_response(text, done_reason, prompt_tokens))


def error(status: int) -> httpx.Response:
    return httpx.Response(status, json={"error": f"echo {PROMPT_MARKER}"})


def client_for(handler: object, model: str = DEFAULT_MODEL) -> LLMClient:
    return LLMClient(model, DEFAULT_HOST, transport=httpx.MockTransport(handler))


def call(client: LLMClient, timeout_s: float = 90.0) -> object:
    return client.complete_json(system="system text", user=PROMPT_MARKER, json_schema=SCHEMA, timeout_s=timeout_s)


def test_request_shape() -> None:
    server = Server(ok('{"a": 1}'))
    assert call(client_for(server)) == '{"a": 1}'

    request = server.requests[0]
    assert request.url.host == "127.0.0.1"
    assert request.url.path == "/api/chat"
    body = server.bodies[0]
    assert body["model"] == DEFAULT_MODEL
    assert body["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": PROMPT_MARKER},
    ]
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"]["temperature"] == 0
    assert body["options"]["num_ctx"] == CONTEXT_TOKENS
    assert body["options"]["num_predict"] == MAX_OUTPUT_TOKENS


def test_never_offers_tools() -> None:
    server = Server(ok())
    call(client_for(server))
    assert not server.bodies[0].get("tools")


def test_llm_draft_schema_is_sent_without_references() -> None:
    server = Server(ok())
    call(client_for(server))
    schema = server.bodies[0]["format"]
    serialized = json.dumps(schema)
    assert "$ref" not in serialized
    assert "$defs" not in serialized
    assert schema["additionalProperties"] is False
    assert schema["properties"]["claims"]["items"]["additionalProperties"] is False
    assert set(schema["required"]) == set(LLMDraft.model_fields)
    assert not {"to", "cc", "bcc", "recipients"} & set(schema["properties"])


def test_recursive_schema_is_refused() -> None:
    schema = {
        "$defs": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}}},
        "$ref": "#/$defs/Node",
    }
    with pytest.raises(LLMError, match="unsupported_schema"):
        _inline_refs(schema)


def test_unknown_reference_is_refused() -> None:
    with pytest.raises(LLMError, match="unsupported_schema"):
        _inline_refs({"properties": {"a": {"$ref": "#/$defs/Missing"}}})


def test_reference_keeps_sibling_fields() -> None:
    schema = {"$defs": {"A": {"type": "object"}}, "properties": {"a": {"$ref": "#/$defs/A", "description": "kept"}}}
    assert _inline_refs(schema)["properties"]["a"] == {"type": "object", "description": "kept"}


@pytest.mark.parametrize(
    "host",
    ["https://ollama.com", "http://203.0.113.5:11434", "http://127.0.0.1.evil.example:11434", "http://evil.example"],
)
def test_non_local_hosts_are_refused(host: str) -> None:
    with pytest.raises(LLMError, match="non_local_host"):
        LLMClient(DEFAULT_MODEL, host)


@pytest.mark.parametrize("host", ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"])
def test_local_hosts_are_allowed(host: str) -> None:
    assert LLMClient(DEFAULT_MODEL, host)


@pytest.mark.parametrize("status", [400, 404, 500])
def test_server_errors_become_llm_errors_without_retry(status: int) -> None:
    server = Server(error(status))
    with pytest.raises(LLMError, match=f"status_{status}"):
        call(client_for(server))
    assert len(server.requests) == 1


def test_timeout_is_applied() -> None:
    server = Server(ok())
    call(client_for(server), timeout_s=60)
    assert server.requests[0].extensions["timeout"]["read"] == 60


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
def test_connection_failures_become_llm_errors(failure: type[Exception]) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise failure(f"cannot reach {PROMPT_MARKER}")

    with pytest.raises(LLMError) as raised:
        call(client_for(fail))
    assert PROMPT_MARKER not in str(raised.value)


def test_cut_off_response_raises() -> None:
    with pytest.raises(LLMError, match="length"):
        call(client_for(Server(ok('{"partial": ', "length"))))


def test_prompt_that_filled_the_context_raises() -> None:
    with pytest.raises(LLMError, match="context_exceeded"):
        call(client_for(Server(ok("{}", prompt_tokens=CONTEXT_TOKENS))))


def test_empty_response_raises() -> None:
    with pytest.raises(LLMError, match="no_text_output"):
        call(client_for(Server(ok(""))))


def test_prompt_stays_out_of_errors_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(LLMError) as raised:
        call(client_for(Server(error(400))))
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    assert PROMPT_MARKER not in str(raised.value)
    assert PROMPT_MARKER not in caplog.text


def test_successful_call_logs_no_prompt_or_response(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    call(client_for(Server(ok('{"secret": "RESPONSE-MARKER"}'))))
    assert "done_reason=stop" in caplog.text
    assert PROMPT_MARKER not in caplog.text
    assert "RESPONSE-MARKER" not in caplog.text


def test_settings_come_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.llm.client.load_dotenv", lambda: False)
    monkeypatch.setenv("LLM_MODEL", "other:tag")
    monkeypatch.setenv("LLM_HOST", "http://localhost:1234")
    get_llm_client.cache_clear()
    client = get_llm_client()
    assert (client._model, client._host) == ("other:tag", "http://localhost:1234")
    monkeypatch.delenv("LLM_MODEL")
    monkeypatch.delenv("LLM_HOST")
    get_llm_client.cache_clear()
    client = get_llm_client()
    assert (client._model, client._host) == (DEFAULT_MODEL, DEFAULT_HOST)
    get_llm_client.cache_clear()


def test_non_local_environment_host_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.llm.client.load_dotenv", lambda: False)
    monkeypatch.setenv("LLM_HOST", "https://ollama.com")
    get_llm_client.cache_clear()
    with pytest.raises(LLMError, match="non_local_host"):
        get_llm_client()
    get_llm_client.cache_clear()


def test_drafter_runs_through_the_real_client() -> None:
    server = Server(ok(draft_json()))
    result = _run(make_request(), make_deps(llm=client_for(server)), None, 0)
    assert result.status == "ready_for_review"
    assert result.proposal.to == SENDER
    system, user = server.bodies[0]["messages"]
    assert "My application" not in system["content"]
    assert "My application" in user["content"]


def test_drafter_uses_fallback_when_the_server_is_down() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = _run(make_request(), make_deps(llm=client_for(refuse)), None, 0)
    assert "fallback_template_used" in result.proposal.warnings


class Answer(BaseModel):
    value: int


def test_generate_structured_repairs_once() -> None:
    server = Server(ok("not json"), ok('{"value": 3}'))
    answer = generate_structured(client_for(server), Answer, system="s", user="u", timeout_s=10)
    assert answer.value == 3
    assert len(server.requests) == 2


def test_generate_structured_gives_up_after_repair() -> None:
    server = Server(ok("not json"))
    with pytest.raises(StructuredOutputError):
        generate_structured(client_for(server), Answer, system="s", user="u", timeout_s=10)
    assert len(server.requests) == 2
