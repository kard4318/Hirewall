# Choice node: resolves the candidate's pick strictly against slots offered in this conversation
import re
from collections.abc import Callable
from datetime import tzinfo
from typing import Any

from services.scheduler.conversation.deps import Deps
from services.scheduler.conversation.state import SchedState, slot_to_state, state_to_slot
from services.scheduler.conversation.tokens import token_id

ORDINALS = {"1": 0, "one": 0, "first": 0, "2": 1, "two": 1, "second": 1, "3": 2, "three": 2, "third": 2}
LAST = {"last", "last one", "the last", "the last one"}
WEEKDAY_NAMES = {name: i for i, names in enumerate([
    ("monday", "mon"), ("tuesday", "tue", "tues"), ("wednesday", "wed"), ("thursday", "thu", "thurs"),
    ("friday", "fri"), ("saturday", "sat"), ("sunday", "sun"),
]) for name in names}
REF = re.compile(r"(?:the\s+|#|no\.?\s*|number\s+|option\s+|slot\s+)?(\w+)(?:\s+one)?")


def resolve_slot(ref: str | None, offered: list[dict[str, str]], tz: tzinfo, exact_only: bool) -> dict[str, str] | None:
    """Exact id, ordinal, or a weekday matching exactly one offered slot. Anything else is None."""
    if not ref or not offered:
        return None
    by_id = next((s for s in offered if s["id"] == ref.strip()), None)
    if by_id or exact_only:
        return by_id
    text = ref.strip().lower()
    if text in LAST:
        return offered[-1]
    match = REF.fullmatch(text)
    word = match.group(1) if match else text
    if word in ORDINALS:
        index = ORDINALS[word]
        return offered[index] if index < len(offered) else None
    if word in WEEKDAY_NAMES:
        same_day = [s for s in offered if state_to_slot(s).start.astimezone(tz).weekday() == WEEKDAY_NAMES[word]]
        return same_day[0] if len(same_day) == 1 else None
    return None


def make_node(deps: Deps) -> Callable[[SchedState], dict[str, Any]]:
    def choice(state: SchedState) -> dict[str, Any]:
        candidate = state["candidate"]
        active = deps.bookings.get_active(candidate["candidate_id"], candidate["job_id"])
        if active:
            return {"facts": {"kind": "already_booked", "slot": slot_to_state("booked", active.slot)}}

        understanding = state.get("understanding") or {}
        intent = understanding.get("intent")
        offered = state.get("offered") or []
        pending = state.get("pending_slot_id")
        from_ui = understanding.get("source") == "ui"
        picked = resolve_slot(understanding.get("slot_ref"), offered, deps.config.tz, exact_only=from_ui)

        if intent == "decline":
            return {"pending_slot_id": None, "facts": {"kind": "declined"}}
        if intent == "confirm" and pending and (picked is None or picked["id"] == pending):
            if any(s["id"] == pending for s in offered):
                return {"ready_to_book": True}
        if intent == "confirm" and picked is None:
            return {"facts": {"kind": "need_choice", "slots": offered}}
        # choose_slot, or a confirm that names a different slot: (re)select and ask to confirm.
        if picked is None:
            deps.audit.record("slot_rejected", thread=token_id(state["token"]), from_ui=from_ui)
            return {"facts": {"kind": "unknown_slot", "slots": offered}}
        deps.audit.record("slot_chosen", thread=token_id(state["token"]), slot_id=picked["id"])
        return {"pending_slot_id": picked["id"], "facts": {"kind": "confirm_slot", "slot": picked}}

    return choice


def route(state: SchedState) -> str:
    return "book" if state.get("ready_to_book") else "reply"
