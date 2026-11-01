# Configuration for the scheduler service
import os
from dataclasses import dataclass, field
from datetime import time, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_TIMEZONE = "Africa/Tunis"

WORK_START = time(9, 0)
WORK_END = time(17, 0)
SLOT_MINUTES = 45
BUFFER_MINUTES = 15
STEP_MINUTES = 30
DAYS = 5  # working days to search
MAX_SLOTS = 3
PER_DAY = 1

SEND_UPDATES_VALUES = ("all", "externalOnly", "none")

# Candidate scheduling conversation
MAX_MESSAGE_CHARS = 500
OFFERED_SLOTS = 3
WINDOW_DAYS = 10  # calendar days searched for free slots
TOKEN_TTL_HOURS = 72
# Abuse limits per booking link
MAX_MESSAGES_PER_MINUTE = 10
MAX_TURNS = 40
MAX_SLOT_SEARCHES = 6  # caps how much of the HR calendar one link can reveal


def get_timezone() -> tzinfo:
    name = os.getenv("SCHEDULER_TIMEZONE", DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name.upper() == "UTC":
            return timezone.utc
        raise ValueError(f"Unknown SCHEDULER_TIMEZONE {name!r} (on Windows, `pip install tzdata`)")


def get_send_updates() -> str:
    value = os.getenv("SEND_UPDATES", "none")
    if value not in SEND_UPDATES_VALUES:
        raise ValueError(f"SEND_UPDATES must be one of {SEND_UPDATES_VALUES}, got {value!r}")
    return value


def resolve_path(value: str) -> Path:
    """Resolve a path from env relative to the repo root, so it works from any cwd."""
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def get_hr_notification_email() -> str | None:
    return os.getenv("HR_NOTIFICATION_EMAIL", "").strip() or None


def get_strict_booking_mode() -> bool:
    return os.getenv("STRICT_BOOKING_MODE", "false").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class ConversationSettings:
    """Settings for the candidate scheduling conversation; tests build it directly."""

    tz: tzinfo = field(default_factory=get_timezone)
    hr_email: str | None = field(default_factory=get_hr_notification_email)
    strict_booking: bool = field(default_factory=get_strict_booking_mode)
    max_message_chars: int = MAX_MESSAGE_CHARS
    offered_slots: int = OFFERED_SLOTS
    window_days: int = WINDOW_DAYS
    token_ttl_hours: int = TOKEN_TTL_HOURS
    slot_minutes: int = SLOT_MINUTES
    buffer_minutes: int = BUFFER_MINUTES
    max_messages_per_minute: int = MAX_MESSAGES_PER_MINUTE
    max_turns: int = MAX_TURNS
    max_slot_searches: int = MAX_SLOT_SEARCHES
