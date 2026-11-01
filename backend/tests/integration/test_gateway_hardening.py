"""Gateway hardening: security headers, rate limits, body size, CORS, request logs and generic errors."""
import logging

import pytest
from fastapi.testclient import TestClient

from gateway.config import GatewaySettings
from gateway.main import create_app
from gateway.middleware.cors import CorsConfigError
from gateway.middleware.rate_limit import _token_key, is_llm_route
from services.scheduler.service import SchedulingService
from services.scheduler.tests.conversation_harness import make_harness

ORIGIN = "http://localhost:5173"


@pytest.fixture
def build(monkeypatch: pytest.MonkeyPatch):
    harness = make_harness(monkeypatch)
    monkeypatch.setenv("HR_TOKEN_SECRET", "hr-secret-for-hardening-tests")

    def make(**settings):
        values = {"requests_per_minute": 1000, "llm_requests_per_minute": 1000, "max_body_bytes": 1024 * 1024,
                  "allowed_origins": (ORIGIN,), "hsts": False, **settings}
        app = create_app(SchedulingService(harness.deps, None, harness.deps.bookings), settings=GatewaySettings(**values))
        return app, TestClient(app, raise_server_exceptions=False)

    return make


def test_security_headers_on_every_response(build):
    _, client = build()
    for response in (client.get("/api/meta"), client.get("/api/hr/me"), client.get("/nowhere")):
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "camera=()" in response.headers["permissions-policy"]
        assert response.headers["cache-control"] == "no-store"
        assert "strict-transport-security" not in response.headers


def test_hsts_only_when_enabled(build):
    _, client = build(hsts=True)
    assert client.get("/api/meta").headers["strict-transport-security"].startswith("max-age=31536000")


def test_general_rate_limit(build):
    _, client = build(requests_per_minute=3)
    codes = [client.get("/api/meta").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    response = client.get("/api/meta")
    assert response.json() == {"detail": "rate_limited"} and response.headers["retry-after"] == "60"


def test_model_routes_have_a_stricter_limit(build):
    _, client = build(llm_requests_per_minute=2)
    codes = [client.post("/api/knowledge/ask", json={"question": "hi"}).status_code for _ in range(3)]
    assert codes[:2] == [401, 401] and codes[2] == 429
    assert client.post("/api/knowledge/ask", json={}).json() == {"detail": "rate_limited_model"}
    assert client.get("/api/meta").status_code == 200  # ordinary routes keep working


@pytest.mark.parametrize(("method", "path", "llm"), [
    ("POST", "/api/hr/inbox/e-1/draft", True), ("POST", "/api/schedule/abc/message", True),
    ("POST", "/api/screener/jobs/job-1/runs", True), ("GET", "/api/hr/inbox/e-1/draft", False),
    ("POST", "/api/hr/approvals/x/decision", False),
])
def test_model_routes_are_recognised(method, path, llm):
    assert is_llm_route(method, path) is llm


def test_tokens_are_counted_by_hash_only():
    key = _token_key([(b"authorization", b"Bearer hr.secret-token.sig")])
    assert key and "secret" not in key and len(key) == 24
    assert _token_key([(b"authorization", b"Basic abc")]) is None


def test_declared_body_over_the_limit_is_refused(build):
    _, client = build(max_body_bytes=200)
    response = client.post("/api/hr/login", json={"username": "a", "password": "x" * 500})
    assert (response.status_code, response.json()) == (413, {"detail": "body_too_large"})


def test_streamed_body_over_the_limit_is_refused(build):
    _, client = build(max_body_bytes=200)

    def chunks():
        yield b'{"username": "a", "password": "'
        yield b"x" * 500
        yield b'"}'

    response = client.post("/api/hr/login", content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_upload_routes_keep_their_own_limit(build):
    _, client = build(max_body_bytes=200)
    response = client.post("/api/screener/candidates", files=[("files", ("a.pdf", b"%PDF-" + b"0" * 1000))])
    assert response.status_code == 401  # reached the route, which asks for a login


def test_cors_allowlist(build):
    _, client = build()
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"}
    allowed = client.options("/api/hr/login", headers={"Origin": ORIGIN, **preflight})
    assert allowed.headers.get("access-control-allow-origin") == ORIGIN
    assert "access-control-allow-credentials" not in allowed.headers
    evil = client.options("/api/hr/login", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in evil.headers
    assert "access-control-allow-origin" not in client.get("/api/meta", headers={"Origin": "https://evil.example"}).headers


def test_wildcard_origin_is_refused(build):
    with pytest.raises(CorsConfigError):
        build(allowed_origins=("*",))


def test_request_log_uses_the_route_template(build, caplog):
    _, client = build()
    caplog.set_level(logging.INFO, logger="hirewall.request")
    response = client.post("/api/schedule/secret-candidate-token/message?x=private", json={"text": "my phone 12345678"})
    line = caplog.records[-1].getMessage()
    assert "route=/api/schedule/{token}/message" in line and f"status={response.status_code}" in line
    assert response.headers["x-request-id"] in line
    for private in ("secret-candidate-token", "private", "12345678"):
        assert private not in caplog.text


def test_request_id_from_the_client_only_when_safe(build):
    _, client = build()
    assert client.get("/api/meta", headers={"X-Request-ID": "abcdef12-3456"}).headers["x-request-id"] == "abcdef12-3456"
    assert client.get("/api/meta", headers={"X-Request-ID": "<script>"}).headers["x-request-id"] != "<script>"


def test_unexpected_errors_are_generic(build, caplog):
    app, client = build()

    @app.get("/api/boom")
    def boom() -> None:
        raise RuntimeError("database password is hunter2 for ines@example.test")

    caplog.set_level(logging.ERROR)
    response = client.get("/api/boom")
    assert response.status_code == 500 and response.json()["detail"] == "internal_error"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "hunter2" not in response.text and "hunter2" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_validation_errors_do_not_echo_input(build):
    _, client = build()
    response = client.post("/api/hr/login", json={"username": "ines@example.test", "extra": "Ines Kacem 12345678"})
    body = response.json()
    assert response.status_code == 422 and body["detail"] == "invalid_request"
    assert "Kacem" not in response.text and "ines@example.test" not in response.text
    assert {tuple(f["loc"]) for f in body["fields"]} >= {("body", "password"), ("body", "extra")}
