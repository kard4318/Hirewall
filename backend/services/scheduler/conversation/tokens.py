# Signed booking-link tokens (stdlib HMAC-SHA256) identifying one candidate and job
import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class TokenError(ValueError):
    """Token is malformed, tampered with, or expired."""


class TokenSecretError(RuntimeError):
    """SCHEDULER_TOKEN_SECRET is not configured."""


@dataclass(frozen=True)
class TokenPayload:
    candidate_id: str
    job_id: str
    expires_at: datetime


def _secret(secret: str | None) -> bytes:
    value = secret if secret is not None else os.getenv("SCHEDULER_TOKEN_SECRET", "")
    if not value:
        raise TokenSecretError("SCHEDULER_TOKEN_SECRET is not set; add a long random value to .env.")
    return value.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str, secret: bytes) -> str:
    return _b64(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())


def create_token(candidate_id: str, job_id: str, ttl_hours: int, now: datetime, secret: str | None = None) -> str:
    expires = int((now + timedelta(hours=ttl_hours)).timestamp())
    nonce = secrets.token_urlsafe(6)  # every issued link is unique, even within the same second
    body = _b64(json.dumps({"c": candidate_id, "j": job_id, "exp": expires, "n": nonce},
                           separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body, _secret(secret))}"


def verify_token(token: str, now: datetime, secret: str | None = None) -> TokenPayload:
    key = _secret(secret)
    if not isinstance(token, str) or not token.isascii() or token.count(".") != 1 or len(token) > 512:
        raise TokenError("bad format")
    body, signature = token.split(".")
    if not hmac.compare_digest(signature, _sign(body, key)):
        raise TokenError("bad signature")
    try:
        data = json.loads(_unb64(body))
        payload = TokenPayload(
            candidate_id=str(data["c"]),
            job_id=str(data["j"]),
            expires_at=datetime.fromtimestamp(int(data["exp"]), tz=timezone.utc),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise TokenError("bad format") from exc
    if now >= payload.expires_at:
        raise TokenError("expired")
    return payload


def token_id(token: str) -> str:
    """Stable, non-secret id for a token; used as the LangGraph thread_id."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
