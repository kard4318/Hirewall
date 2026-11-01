# Per-IP and per-token request limits, stricter on routes that run the local model (protects the GPU)
"""In memory, so limits are per server process. Tokens are counted by a hash, never stored as written."""
import hashlib
import re
import threading
import time
from collections import deque

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

WINDOW_SECONDS = 60.0

# Routes where one request can mean one or more model calls.
LLM_ROUTES = tuple(re.compile(pattern) for pattern in (
    r"^/api/hr/inbox/[^/]+/(?:triage|draft|decision)$",
    r"^/api/schedule/[^/]+/message$",
    r"^/api/knowledge/ask$",
    r"^/api/hr/digest/generate$",
    r"^/api/screener/candidates(?:/demo)?$",
    r"^/api/screener/jobs/extract$",
    r"^/api/screener/jobs/[^/]+/runs$",
))


def is_llm_route(method: str, path: str) -> bool:
    return method == "POST" and any(pattern.match(path) for pattern in LLM_ROUTES)


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, now: float) -> bool:
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True


def _token_key(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, value in headers:
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            if scheme.lower() == "bearer" and token:
                return hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    return None


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, requests_per_minute: int, llm_requests_per_minute: int,
                 clock=time.monotonic) -> None:  # noqa: ANN001
        self.app = app
        self.general = requests_per_minute
        self.llm = llm_requests_per_minute
        self.window = SlidingWindow()
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        now = self.clock()
        client = (scope.get("client") or ("unknown", 0))[0]
        keys = [f"ip:{client}"]
        token = _token_key(scope.get("headers", []))
        if token:
            keys.append(f"token:{token}")
        checks = [(key, self.general) for key in keys]
        if is_llm_route(scope["method"], scope["path"]):
            checks += [(f"llm:{key}", self.llm) for key in keys]
            reason = "rate_limited_model"
        else:
            reason = "rate_limited"
        for key, limit in checks:
            if not self.window.allow(key, limit, now):
                response = JSONResponse({"detail": reason}, status_code=429, headers={"Retry-After": "60"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
