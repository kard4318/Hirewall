# Named staff accounts: a local users file, scrypt password hashes, and lockout after repeated failures
"""Users live in a JSON file outside git (HIREWALL_USERS_FILE, default data/runtime/users.json).

Passwords are hashed with scrypt from the standard library. The file holds no passwords.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from core.paths import REPO_ROOT
from gateway.auth.roles import is_role

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,39}$")
MIN_PASSWORD = 10
# Interactive-login strength: about 64 MiB and well under a second per check.
_N, _R, _P = 2**14, 8, 1
_DUMMY_HASH = None  # computed once, so an unknown username costs the same time as a known one


class UserError(ValueError):
    """A short reason code: invalid_username, unknown_role, weak_password, user_exists, unknown_user."""


def users_file() -> Path:
    return Path(os.getenv("HIREWALL_USERS_FILE") or REPO_ROOT / "data" / "runtime" / "users.json")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32, maxmem=128 * 1024 * 1024)
    encode = lambda raw: base64.b64encode(raw).decode("ascii")  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${encode(salt)}${encode(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                dklen=len(expected), maxmem=128 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    role: str
    password_hash: str


class UserStore:
    """Read from disk on each check, so users added with scripts/create_user.py work without a restart."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or users_file()
        self._lock = threading.Lock()

    def _load(self) -> dict[str, User]:
        if not self.path.is_file():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        users = {}
        for item in raw.get("users", []):
            user = User(item["username"], item.get("display_name", item["username"]), item["role"],
                        item.get("password_hash", ""))
            if is_role(user.role):
                users[user.username] = user
        return users

    def get(self, username: str) -> User | None:
        return self._load().get(username)

    def list(self) -> list[User]:
        return sorted(self._load().values(), key=lambda user: user.username)

    def _save(self, users: dict[str, User]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"users": [asdict(user) for user in sorted(users.values(), key=lambda u: u.username)]}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def add(self, username: str, display_name: str, role: str, password: str) -> User:
        if not USERNAME.match(username):
            raise UserError("invalid_username")
        if not is_role(role):
            raise UserError("unknown_role")
        if len(password) < MIN_PASSWORD:
            raise UserError("weak_password")
        with self._lock:
            users = self._load()
            if username in users:
                raise UserError("user_exists")
            user = User(username, " ".join(display_name.split())[:100] or username, role, hash_password(password))
            users[username] = user
            self._save(users)
        return user

    def remove(self, username: str) -> None:
        with self._lock:
            users = self._load()
            if users.pop(username, None) is None:
                raise UserError("unknown_user")
            self._save(users)

    def authenticate(self, username: str, password: str) -> User | None:
        """The user if the password matches. Unknown and disabled users take as long as a wrong password."""
        global _DUMMY_HASH
        user = self.get(username)
        if user is None or not user.password_hash:
            _DUMMY_HASH = _DUMMY_HASH or hash_password("not-a-real-password")
            verify_password(password, _DUMMY_HASH)
            return None
        return user if verify_password(password, user.password_hash) else None


class LoginGuard:
    """Locks a username after `max_failures` wrong passwords in a row, for `lockout`. In memory, per server."""

    def __init__(self, max_failures: int | None = None, lockout: timedelta | None = None) -> None:
        self.max_failures = max_failures or int(os.getenv("LOGIN_MAX_FAILURES", "5"))
        self.lockout = lockout or timedelta(minutes=int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15")))
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def locked(self, username: str, now: datetime) -> bool:
        with self._lock:
            until = self._locked_until.get(username)
            if until and now >= until:
                del self._locked_until[username]
                self._failures.pop(username, None)
                return False
            return until is not None

    def failed(self, username: str, now: datetime) -> bool:
        """Count a failure. True when this failure locks the account."""
        with self._lock:
            self._failures[username] = self._failures.get(username, 0) + 1
            if self._failures[username] >= self.max_failures:
                self._locked_until[username] = now + self.lockout
                return True
            return False

    def succeeded(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username, None)
