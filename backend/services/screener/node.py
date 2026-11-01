# Orchestrator node exposing the screener as a workflow step
"""The screen_job task. Workflow state holds the run id; resume text stays in the screener's store."""
from collections.abc import Callable
from typing import Any

SCREEN_TASK = "screen_job"


def screen_job_node(service: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def run(state: dict[str, Any]) -> dict[str, Any]:
        result = service.execute_run(state["email_id"])  # Orchestrator.start stores the subject id under this key
        update: dict[str, Any] = {"result": {"run_id": result.run_id, "status": result.status}}
        if result.status != "done":
            update.update(status="needs_human", reason_code=result.reason_code)
        return update

    return run
