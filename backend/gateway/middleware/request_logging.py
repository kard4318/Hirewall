# One log line per request: method, route template, status, latency and a request ID; nothing from the request
"""Candidate booking links carry their token in the path, so the raw path, query string, headers and body are
never logged. The route template ("/api/schedule/{token}/message") is."""
import logging
import re
import secrets
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("hirewall.request")
_INCOMING_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def route_template(scope: Scope) -> str:
    route = scope.get("route")
    return getattr(route, "path", None) or "<unmatched>"


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"x-request-id"), "")
        request_id = incoming if _INCOMING_ID.match(incoming) else secrets.token_hex(8)
        scope.setdefault("state", {})["request_id"] = request_id
        started, status = time.perf_counter(), 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode("ascii")))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            logger.info(
                "request id=%s method=%s route=%s status=%s ms=%d",
                request_id, scope["method"], route_template(scope), status, (time.perf_counter() - started) * 1000,
            )
