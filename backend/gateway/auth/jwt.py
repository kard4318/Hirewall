# Signed staff tokens that name a person: who they are (sub) and their role, on top of hr_auth's HMAC format
"""Not a JWT library: the same compact HMAC-SHA256 format as hr_auth, with `sub` and `role` in the payload."""
from dataclasses import dataclass
from datetime import datetime

from gateway.auth.hr_auth import HRAuthError, create_role_token, verify_role_token
from gateway.auth.roles import ROLE_AUDIENCE


@dataclass(frozen=True)
class Principal:
    username: str
    role: str


def issue_token(username: str, role: str, now: datetime) -> str:
    return create_role_token(ROLE_AUDIENCE[role], now, username=username, user_role=role)


def read_token(token: str, now: datetime, audience: str) -> Principal:
    """The person a valid token names. Raises HRAuthError for anything else."""
    payload = verify_role_token(token, now, audience)
    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise HRAuthError("bad subject")
    return Principal(username, payload["role"])
