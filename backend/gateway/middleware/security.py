# Security headers, a request body size limit, and generic error responses for the API
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gateway.middleware.request_logging import route_template

logger = logging.getLogger("hirewall.errors")

# Upload routes check their own, larger limits (5 MB per file, a capped number of files).
UPLOAD_ROUTES = ("/api/screener/candidates", "/api/screener/jobs/extract")

HEADERS = {
    "Cache-Control": "no-store",  # responses carry personal data and booking links
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # The API returns JSON only: nothing in a response may load, run or be framed.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}
HSTS = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool = False) -> None:
        self.app = app
        self.headers = [(k.lower().encode(), v.encode()) for k, v in HEADERS.items()]
        if hsts:  # only meaningful, and only safe to send, when the site is served over HTTPS
            self.headers.append((b"strict-transport-security", HSTS.encode()))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                names = {name for name, _ in message.get("headers", [])}
                message.setdefault("headers", []).extend(h for h in self.headers if h[0] not in names)
            await send(message)

        await self.app(scope, receive, with_headers)


class BodySizeMiddleware:
    """Refuses bodies over `limit` bytes, whether the client declares the size or streams it.

    Only the body of the request is counted, so a response of any size is unaffected.
    """

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in UPLOAD_ROUTES:
            await self.app(scope, receive, send)
            return
        declared = next((v for k, v in scope.get("headers", []) if k == b"content-length"), None)
        if declared is not None and (not declared.isdigit() or int(declared) > self.limit):
            await JSONResponse({"detail": "body_too_large"}, status_code=413)(scope, receive, send)
            return
        # Non-upload bodies are small JSON, so they are read here in full before any route sees them.
        chunks, received = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            received += len(chunk)
            if received > self.limit:
                await JSONResponse({"detail": "body_too_large"}, status_code=413)(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body, replayed = b"".join(chunks), False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def install_error_handlers(app: FastAPI) -> None:
    """Clients get a short code and the request ID. Stack traces and messages stay out of responses."""

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        # Only where and what kind: never the submitted value, which may hold personal data.
        fields = [{"loc": [str(part) for part in item.get("loc", ())], "type": item.get("type")} for item in error.errors()]
        return JSONResponse({"detail": "invalid_request", "fields": fields}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        request_id = request.scope.get("state", {}).get("request_id")
        # The message of an exception can quote user data, so only its type is logged.
        logger.error("unhandled error id=%s route=%s type=%s", request_id, route_template(request.scope),
                     type(error).__name__)
        # This response is built outside the other middleware, so it carries the headers itself.
        headers = {**HEADERS, **({"X-Request-ID": request_id} if request_id else {})}
        return JSONResponse({"detail": "internal_error", "request_id": request_id}, status_code=500, headers=headers)
