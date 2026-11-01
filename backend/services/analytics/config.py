# Configuration for People Analytics: reference date, privacy threshold, data paths and minutes saved per task
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Estimated minutes of HR work an agent action saves (used for the "hours saved" estimate only).
MINUTES_SAVED = {
    ("resume_screened", None): 6,
    ("booking_created", None): 4,
    ("kb_question", "answered"): 3,
    ("reminder_drafted", None): 2,
    ("approval_decided", None): 1,
}
DEPARTMENTS = ["Engineering", "Support", "Sales", "Product & Design", "Operations", "People & Finance"]
SITES = ["Tunis", "Paris", "Remote"]
CONTRACTS = ["permanent", "fixed_term", "intern"]
AGE_BANDS = ["<25", "25-34", "35-44", "45-54", "55+"]
GENDERS = ["F", "M", "undisclosed"]
TENURE_BANDS = ["<1y", "1-2y", "2-3y", "3-5y", "5y+"]


@dataclass(frozen=True)
class AnalyticsSettings:
    as_of: date = field(default_factory=lambda: date.fromisoformat(os.getenv("ANALYTICS_AS_OF") or "2026-11-01"))
    min_group_size: int = field(default_factory=lambda: int(os.getenv("MIN_GROUP_SIZE") or 5))
    people_dir: Path = REPO_ROOT / "data" / "people"
    audit_file: Path = REPO_ROOT / "data" / "runtime" / "audit_events.jsonl"
