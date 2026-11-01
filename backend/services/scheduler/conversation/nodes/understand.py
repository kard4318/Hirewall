# Understand node: UI actions map deterministically; free text goes through the LLM into a strict schema
from collections.abc import Callable
from string import Template
from typing import Any

from services.scheduler.conversation.deps import Deps
from services.scheduler.conversation.llm import StructuredOutputError, load_prompt, structured, wrap_untrusted
from services.scheduler.conversation.schemas import Understanding
from services.scheduler.conversation.state import SchedState

UI_INTENTS = {"choose": "choose_slot", "confirm": "confirm", "decline": "decline"}


def make_node(deps: Deps) -> Callable[[SchedState], dict[str, Any]]:
    template = Template(load_prompt("understand.md"))

    def understand(state: SchedState) -> dict[str, Any]:
        action = state.get("ui_action")
        if action:
            result = Understanding(intent=UI_INTENTS[action["type"]], slot_ref=action.get("slot_id"))
            return {"understanding": {**result.model_dump(mode="json"), "source": "ui"}}

        now = deps.clock.now().astimezone(deps.config.tz)
        offered = state.get("offered") or []
        system = template.safe_substitute(
            today=now.date().isoformat(),
            weekday=f"{now:%A}",
            timezone=str(deps.config.tz),
            offered=", ".join(f"{i}) id {s['id']}" for i, s in enumerate(offered, start=1)) or "none",
            pending="yes" if state.get("pending_slot_id") else "no",
        )
        try:
            result = structured(deps.llm, system, wrap_untrusted(state.get("user_message") or ""), Understanding)
            source = "llm"
        except StructuredOutputError:
            deps.audit.record("llm_fallback", step="understand")
            result, source = Understanding(intent="other"), "fallback"
        return {"understanding": {**result.model_dump(mode="json"), "source": source}}

    return understand


def route(state: SchedState) -> str:
    intent = (state.get("understanding") or {}).get("intent")
    if intent == "ask_slots":
        return "find_slots"
    if intent in ("choose_slot", "confirm", "decline"):
        return "choice"
    return "answer"
