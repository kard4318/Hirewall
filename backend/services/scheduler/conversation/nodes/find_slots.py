# Find-slots node: reads busy times (read-only) and computes free slots in code, never via the LLM
import dataclasses
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any

from services.scheduler.availability import SlotConstraints, find_free_slots, stable_slot_id
from services.scheduler.conversation.deps import Deps
from services.scheduler.conversation.schemas import Preference
from services.scheduler.conversation.state import SchedState, slot_to_state
from services.scheduler.conversation.tokens import token_id


def compute_offers(
    deps: Deps, preference: Preference | None, exclude_starts: frozenset[datetime] = frozenset()
) -> tuple[list[dict[str, str]], str | None]:
    """(offered slots, reason when empty). Busy times are read for the whole window up front."""
    cfg = deps.config
    now = deps.clock.now().astimezone(cfg.tz)
    first_day = now.date()
    last_day = first_day + timedelta(days=cfg.window_days - 1)
    window_end = datetime.combine(last_day + timedelta(days=1), time(0), tzinfo=cfg.tz)
    working_days = sum((first_day + timedelta(days=i)).weekday() < 5 for i in range(cfg.window_days))

    constraints = preference.to_constraints() if preference else SlotConstraints()
    if exclude_starts:
        constraints = dataclasses.replace(constraints, exclude_starts=exclude_starts)
    busy = deps.calendar.get_busy(now, window_end)
    slots = find_free_slots(
        busy, now, cfg.tz,
        slot_minutes=cfg.slot_minutes, buffer_minutes=cfg.buffer_minutes,
        days=working_days, max_slots=cfg.offered_slots, constraints=constraints,
    )
    offered = [slot_to_state(stable_slot_id(s.start), s) for s in slots]
    if offered:
        return offered, None
    return [], "no_more" if exclude_starts else _no_slot_reason(constraints, first_day, last_day)


def _no_slot_reason(c: SlotConstraints, first_day: Any, last_day: Any) -> str:
    if (c.dates_from and c.dates_from > last_day) or (c.dates_to and c.dates_to < first_day):
        return "outside_window"
    if (c.single_date() and c.dates_from.weekday() >= 5) or (c.weekdays is not None and c.weekdays <= {5, 6}):
        return "weekend"
    if c.single_date():
        return "fully_booked"
    return "no_match"


def make_node(deps: Deps) -> Callable[[SchedState], dict[str, Any]]:
    def find_slots(state: SchedState) -> dict[str, Any]:
        candidate = state["candidate"]
        active = deps.bookings.get_active(candidate["candidate_id"], candidate["job_id"])
        if active:
            return {"facts": {"kind": "already_booked", "slot": slot_to_state("booked", active.slot)}}

        thread = token_id(state["token"])
        searches = state.get("slot_searches") or 0
        if searches >= deps.config.max_slot_searches:  # stops one link from mapping the whole HR calendar
            deps.audit.record("search_limit_reached", thread=thread)
            return {"facts": {"kind": "search_limit"}}

        understanding = state.get("understanding") or {}
        raw = understanding.get("preference")
        preference = Preference.model_validate(raw) if raw else None
        has_preference = bool(preference and preference.model_dump(exclude_defaults=True))
        shown = state.get("shown_starts") or []
        more = bool(understanding.get("more_options")) and bool(shown)
        exclude = frozenset(datetime.fromisoformat(s) for s in shown) if more else frozenset()

        offered, reason = compute_offers(deps, preference, exclude)
        if not offered:
            deps.audit.record("no_slots", thread=thread, reason=reason)
            return {"slot_searches": searches + 1, "facts": {"kind": "no_slots", "reason": reason}}
        deps.audit.record("slots_offered", thread=thread, slot_ids=[s["id"] for s in offered], more=more)
        starts = [s["start"] for s in offered]
        return {
            "slot_searches": searches + 1,
            "offered": offered,
            "pending_slot_id": None,
            "shown_starts": (shown + starts) if more else starts,
            "facts": {"kind": "slots_offered", "slots": offered, "more": more, "preference": has_preference},
        }

    return find_slots
