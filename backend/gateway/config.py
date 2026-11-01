# Gateway security settings from .env: rate limits, body size, allowed origins, HSTS
import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _origins() -> tuple[str, ...]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return tuple(origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip())


@dataclass(frozen=True)
class GatewaySettings:
    """Read when the app is built, after .env is loaded."""

    requests_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 300))
    llm_requests_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_LLM_PER_MINUTE", 12))
    max_body_bytes: int = field(default_factory=lambda: _int("MAX_BODY_BYTES", 1024 * 1024))
    allowed_origins: tuple[str, ...] = field(default_factory=_origins)
    hsts: bool = field(default_factory=lambda: os.getenv("HSTS_ENABLED", "false").strip().lower() in ("1", "true", "yes"))
