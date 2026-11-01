# Default locations for demo data and local runtime files

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return Path(os.getenv("HIREWALL_DATA_DIR") or REPO_ROOT / "data")


def runtime_dir() -> Path:
    return Path(os.getenv("HIREWALL_RUNTIME_DIR") or REPO_ROOT / ".runtime")
