# Staff authentication: HMAC-signed bearer tokens for HR and employees, separate from candidate links
import base64
import hashlib
import hmac
import json
import os
from collections import deque
from datetime import datetime, timedelta, timezone

HR_TOKEN_TTL_HOURS = 8
# audience -> (token prefix, legacy passcode env var). Staff tokens have three dot-separated parts and candidate links
# two, and the audience is part of the signature, so no token works for another audience.
ROLES = {"hr": ("hr.", "HR_PASSCODE"), "employee": ("emp.", "EMPLOYEE_PASSCODE")}
# Which staff roles may hold a token for each audience (see gateway/auth/roles.py), and the default for test tokens.
AUDIENCE_ROLES = {"hr": ("hr_admin", "recruiter"), "employee": ("employee",)}


class HRAuthError(Exception):
    """Missing, malformed, tampered or expired HR token, or wrong passcode."""


class HRAuthConfigError(RuntimeError):
    """HR_PASSCODE / HR_TOKEN_SECRET are missing or unsafe."""


def _secret() -> bytes:
    secret = os.getenv("HR_TOKEN_SECRET", "")
    if not secret:
        raise HRAuthConfigError("HR_TOKEN_SECRET is not set.")
    if secret == os.getenv("SCHEDULER_TOKEN_SECRET", ""):
        raise HRAuthConfigError("HR_TOKEN_SECRET must differ from SCHEDULER_TOKEN_SECRET.")
    return secret.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str, audience: str) -> str:
    return _b64(hmac.new(_secret(), f"{audience}|{body}".encode("ascii"), hashlib.sha256).digest())


def check_passcode(passcode: str, role: str = "hr") -> bool:
    """Legacy shared-passcode check. No route uses it since named accounts replaced passcodes."""
    env = ROLES[role][1]
    expected = os.getenv(env, "")
    if not expected:
        raise HRAuthConfigError(f"{env} is not set.")
    return hmac.compare_digest(passcode.encode("utf-8"), expected.encode("utf-8"))


def create_role_token(role: str, now: datetime, username: str | None = None, user_role: str | None = None) -> str:
    """`role` is the audience (hr or employee). `username` and `user_role` name the person; tests may omit them."""
    prefix = ROLES[role][0]
    user_role = user_role or AUDIENCE_ROLES[role][0]
    if user_role not in AUDIENCE_ROLES[role]:
        raise ValueError("role not allowed for this audience")
    expires = int((now + timedelta(hours=HR_TOKEN_TTL_HOURS)).timestamp())
    payload = {"aud": role, "sub": username or role, "role": user_role, "exp": expires}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{prefix}{body}.{_sign(body, role)}"


def verify_role_token(token: str, now: datetime, role: str) -> dict:
    prefix = ROLES[role][0]
    if not token.isascii() or not token.startswith(prefix) or token.count(".") != 2 or len(token) > 512:
        raise HRAuthError("bad format")
    body, signature = token[len(prefix):].split(".")
    if not hmac.compare_digest(signature, _sign(body, role)):
        raise HRAuthError("bad signature")
    try:
        payload = json.loads(_unb64(body))
        expires = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    except (ValueError, KeyError, TypeError) as exc:
        raise HRAuthError("bad format") from exc
    if payload.get("aud") != role:
        raise HRAuthError("wrong audience")
    if payload.get("role") not in AUDIENCE_ROLES[role]:
        raise HRAuthError("wrong role")
    if now >= expires:
        raise HRAuthError("expired")
    return payload


def create_hr_token(now: datetime) -> str:
    return create_role_token("hr", now)


def verify_hr_token(token: str, now: datetime) -> dict:
    return verify_role_token(token, now, "hr")


class LoginRateLimiter:
    """At most `limit` login attempts per client per window; in memory, enough for one demo server."""

    def __init__(self, limit: int = 5, window: timedelta = timedelta(minutes=1)) -> None:
        self.limit = limit
        self.window = window
        self._attempts: dict[str, deque[datetime]] = {}

    def allow(self, key: str, now: datetime) -> bool:
        attempts = self._attempts.setdefault(key, deque())
        while attempts and now - attempts[0] >= self.window:
            attempts.popleft()
        if len(attempts) >= self.limit:
            return False
        attempts.append(now)
        return True
