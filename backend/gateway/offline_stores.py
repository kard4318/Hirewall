# The scheduler's files, opened without the gateway, for the erasure and retention scripts
from core.paths import REPO_ROOT, runtime_dir
from services.scheduler.conversation.adapters.screener_handoff import ScreenerHandoff
from services.scheduler.scheduling_state import SchedulingStateStore
from services.scheduler.service import erase_screened_records


class OfflineScheduler:
    """Same erase behaviour as SchedulingService.erase_screened, on the files it would use."""

    def __init__(self) -> None:
        self.state = SchedulingStateStore(REPO_ROOT / "data" / "runtime" / "scheduling_state.json")
        self.handoff = ScreenerHandoff(runtime_dir() / "scheduler_handoff.json")

    def erase_screened(self, screener_candidate_id: str) -> int:
        return erase_screened_records(screener_candidate_id, self.state, self.handoff)[0]
