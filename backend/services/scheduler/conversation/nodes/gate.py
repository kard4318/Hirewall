# Gate node: verifies the booking token and candidate, rate-limits the link, and screens the message
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from services.scheduler.conversation.deps import Deps
from services.scheduler.conversation.guard import clean_message, screen
from services.scheduler.conversation.state import SchedState
from services.scheduler.conversation.tokens import TokenError, token_id, verify_token

APPROVED_STATUS = "approved_for_interview"
UI_ACTIONS = {"choose", "confirm", "decline"}

# Fresh per-turn values; persisted fields (offered, pending_slot_id, booking, counters) are left alone.
TURN_RESET: dict[str, Any] = {
    "blocked": False, "block_reason": None, "understanding": None,
    "ready_to_book": False, "facts": None, "reply": None,
}


def external_security_check(text: str) -> str | None:
    """HOOK: call backend/security (sanitizer, injection_detector) here once it exists.

    Return a block reason string to block the message, or None to let it through.
    """
    return None


def valid_ui_action(action: Any) -> bool:
    if not isinstance(action, dict) or action.get("type") not in UI_ACTIONS:
        return False
    if action["type"] == "choose":
        slot_id = action.get("slot_id")
        return isinstance(slot_id, str) and 0 < len(slot_id) <= 32
    return True


def make_node(deps: Deps) -> Callable[[SchedState], dict[str, Any]]:
    cfg = deps.config

    def block(state: SchedState, reason: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        token = state.get("token")
        deps.audit.record("message_blocked", reason=reason,
                          thread=token_id(token) if isinstance(token, str) else None)
        return {**TURN_RESET, "candidate": None, **(extra or {}), "user_message": "", "blocked": True,
                "block_reason": reason, "facts": {"kind": "blocked", "reason": reason}}

    def gate(state: SchedState) -> dict[str, Any]:
        now = deps.clock.now()
        try:
            payload = verify_token(state.get("token") or "", now)
        except TokenError:
            return block(state, "invalid_token")

        # Per-link limits: a leaked link must not flood the LLM or the calendar.
        recent = [t for t in state.get("recent_turns") or [] if now - datetime.fromisoformat(t) < timedelta(minutes=1)]
        counters = {"turns": (state.get("turns") or 0) + 1, "recent_turns": [*recent, now.isoformat()]}
        if len(recent) >= cfg.max_messages_per_minute:
            return block(state, "rate_limited", counters)
        if counters["turns"] > cfg.max_turns:
            return block(state, "turn_limit", counters)

        record = deps.candidates.get_candidate(payload.candidate_id)
        if not record or record.get("job_id") != payload.job_id:
            return block(state, "unknown_candidate", counters)
        if record.get("status") != APPROVED_STATUS:
            return block(state, "not_approved", counters)
        # Only what the conversation needs is kept in graph state; email is fetched again at booking time.
        candidate = {
            "candidate_id": payload.candidate_id,
            "job_id": payload.job_id,
            "first_name": record["first_name"],
            "job_title": record["job_title"],
        }
        ok = {**TURN_RESET, **counters, "candidate": candidate}

        action = state.get("ui_action")
        if action is not None:
            if not valid_ui_action(action):
                return block(state, "bad_action", {**counters, "candidate": candidate})
            return {**ok, "user_message": ""}

        text = clean_message(state.get("user_message") or "")
        if not text:
            return block(state, "empty_message", {**counters, "candidate": candidate})
        if len(text) > cfg.max_message_chars:
            return block(state, "message_too_long", {**counters, "candidate": candidate})
        reason = screen(text) or external_security_check(text)
        if reason:
            return block(state, reason, {**counters, "candidate": candidate})
        return {**ok, "user_message": text}

    return gate
