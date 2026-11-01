# Persistence of workflow checkpoints for pause/resume

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from core.paths import runtime_dir

CHECKPOINT_FILE = "workflow_checkpoints.sqlite3"


def open_checkpointer(path: Path | None = None) -> SqliteSaver:
    """Open saved workflows, so a paused draft survives a restart and can be approved later."""
    path = path or runtime_dir() / CHECKPOINT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(path, check_same_thread=False))
    saver.setup()
    return saver
