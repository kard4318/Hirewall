# Resets the demo: deletes saved candidate statuses and bookings, and the employee question log, in data/runtime/
import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1] / "data" / "runtime"
FILES = {
    "scheduling_state.json": "every candidate is back to 'passed'",
    "knowledge_log.json": "the HR question desk is empty",
}


def main() -> int:
    for name, effect in FILES.items():
        path = RUNTIME / name
        if path.is_file():
            path.unlink()
            print(f"Deleted data/runtime/{name}: {effect}.")
        else:
            print(f"Nothing to reset for data/runtime/{name}.")
    print("Restart the backend so it forgets in-memory state. Events already created in Google Calendar stay there;")
    print("cancel them from the HR page before resetting, or delete them in Google Calendar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
