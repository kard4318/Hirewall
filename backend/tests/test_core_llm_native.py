# Tests for core/llm plain-text clients: the stdlib Ollama provider (local /api/chat stub) and structured()
import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import BaseModel

from core.llm.client import FakeLLM, LLMConfigError, LLMError, LLMUnavailableError, OllamaLLM, get_llm
from core.llm.structured_output import StructuredOutputError, structured


class FakeOllama(BaseHTTPRequestHandler):
    behaviour = "ok"     # ok | missing | slow
    last_body: dict = {}

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        FakeOllama.last_body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/api/chat":
            self.send_response(404)
            self.end_headers()
            return
        if FakeOllama.behaviour == "missing":
            self._json(404, {"error": "model 'nope' not found"})
            return
        if FakeOllama.behaviour == "slow":
            time.sleep(1.5)
        self._json(200, {"message": {"role": "assistant", "content": "<think>hidden</think>{\"ok\": true}"}})

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    FakeOllama.behaviour = "ok"
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_success_strips_reasoning_and_sends_options(server: str) -> None:
    llm = OllamaLLM("qwen-test", host=server, num_ctx=4096, timeout=5)
    assert llm.generate("sys", "hello") == '{"ok": true}'
    body = FakeOllama.last_body
    assert body["model"] == "qwen-test" and body["stream"] is False and body["think"] is False
    assert body["options"] == {"temperature": 0, "num_ctx": 4096}
    assert [m["role"] for m in body["messages"]] == ["system", "user"] and "format" not in body


def test_json_mode_sets_format(server: str) -> None:
    OllamaLLM("qwen-test", host=server, timeout=5).generate("sys", "hello", json_mode=True)
    assert FakeOllama.last_body["format"] == "json"


def test_connection_refused_says_start_ollama() -> None:
    # Windows takes about 2s to refuse a closed local port, so leave room before the client times out.
    llm = OllamaLLM("qwen-test", host=f"http://127.0.0.1:{free_port()}", timeout=15)
    with pytest.raises(LLMUnavailableError, match="Start Ollama"):
        llm.generate("sys", "hello")


def test_missing_model_says_ollama_pull(server: str) -> None:
    FakeOllama.behaviour = "missing"
    with pytest.raises(LLMUnavailableError, match="ollama pull nope"):
        OllamaLLM("nope", host=server, timeout=5).generate("sys", "hello")


def test_timeout_is_a_plain_llm_error(server: str) -> None:
    FakeOllama.behaviour = "slow"
    with pytest.raises(LLMError, match="did not answer") as info:
        OllamaLLM("qwen-test", host=server, timeout=0.3).generate("sys", "hello")
    assert not isinstance(info.value, LLMUnavailableError)


def test_large_prompt_logs_a_warning_without_text(server: str, caplog: pytest.LogCaptureFixture) -> None:
    secret = "confidential-question-text "
    with caplog.at_level(logging.WARNING, logger="core.llm.client"):
        OllamaLLM("qwen-test", host=server, num_ctx=100, timeout=5).generate("sys", secret * 40)
    assert "LLM_NUM_CTX" in caplog.text and "confidential-question-text" not in caplog.text


def test_get_llm_requires_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(LLMConfigError, match="LLM_MODEL"):
        get_llm("ollama")
    monkeypatch.setenv("LLM_MODEL", "qwen3.5:4b")
    monkeypatch.setenv("LLM_NUM_CTX", "2048")
    llm = get_llm("ollama")
    assert isinstance(llm, OllamaLLM) and llm.model == "qwen3.5:4b" and llm.num_ctx == 2048
    fake = FakeLLM(["x"])
    assert get_llm("fake", fake=fake) is fake
    with pytest.raises(LLMConfigError):
        get_llm("openai")


class Pick(BaseModel):
    ok: bool


def test_structured_retries_once_with_the_error() -> None:
    llm = FakeLLM(["nope", '{"ok": true}'])
    assert structured(llm, "sys", "user", Pick).ok is True
    assert "previous output was invalid" in llm.calls[1][1] and llm.calls[1][2] is True


def test_structured_raises_after_two_failures_and_passes_connection_errors_through() -> None:
    with pytest.raises(StructuredOutputError):
        structured(FakeLLM(["nope", "still nope"]), "sys", "user", Pick)

    def down(system: str, user: str, json_mode: bool) -> str:
        raise LLMUnavailableError("Start Ollama")

    llm = FakeLLM(down)
    with pytest.raises(LLMUnavailableError):
        structured(llm, "sys", "user", Pick)
    assert len(llm.calls) == 1  # no pointless retry when Ollama is down
