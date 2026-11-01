# Reply node: fixed templates or validated LLM wording; code fills every date/time placeholder
import re
from collections.abc import Callable
from string import Template
from typing import Any

from services.scheduler.conversation import fallbacks
from services.scheduler.conversation.deps import Deps
from services.scheduler.conversation.formatting import SLOT, SLOTS, format_slot, format_slot_list
from services.scheduler.conversation.llm import StructuredOutputError, load_prompt, structured
from services.scheduler.conversation.schemas import ReplyText
from services.scheduler.conversation.state import SchedState, state_to_slot

LIST_KINDS = {"slots_offered", "need_choice", "slot_taken"}
SINGLE_KINDS = {"confirm_slot", "booked"}


def required_placeholder(kind: str, facts: dict[str, Any]) -> str | None:
    if kind in LIST_KINDS:
        return SLOTS if facts.get("slots") else None
    return SLOT if kind in SINGLE_KINDS else None


def fill(text: str, facts: dict[str, Any], tz: Any) -> str:
    if SLOTS in text:
        text = text.replace(SLOTS, format_slot_list([state_to_slot(s) for s in facts.get("slots") or []], tz))
        text = re.sub(r"\n[ \t]*[.,;:!?]+[ \t]*", "\n", text)  # stray punctuation the LLM put after the list
    if SLOT in text and facts.get("slot"):
        text = text.replace(SLOT, format_slot(state_to_slot(facts["slot"]), tz))
    return text


def variant_of(kind: str, facts: dict[str, Any]) -> str:
    """Finer-grained situation, so the wording matches what the candidate actually asked."""
    if kind == "slots_offered" and facts.get("more"):
        return "slots_offered_more"
    if kind == "slots_offered" and facts.get("preference"):
        return "slots_offered_preference"
    if kind == "no_slots" and facts.get("reason") == "no_more":
        return "no_slots_no_more"
    return kind


def fixed_text(kind: str, facts: dict[str, Any]) -> str:
    if kind == "blocked":
        reason = facts.get("reason")
        if reason in fallbacks.TOKEN_REASONS:
            return fallbacks.LINK_INVALID
        return {"rate_limited": fallbacks.RATE_LIMITED, "turn_limit": fallbacks.TURN_LIMIT}.get(reason, fallbacks.MESSAGE_BLOCKED)
    if kind == "unknown_slot" and not facts.get("slots"):
        return fallbacks.FIXED["unknown_slot_none"]
    return fallbacks.FIXED.get(kind, fallbacks.FIXED["error"])


def make_node(deps: Deps) -> Callable[[SchedState], dict[str, Any]]:
    template = Template(load_prompt("reply.md"))

    def reply(state: SchedState) -> dict[str, Any]:
        facts = state.get("facts") or {"kind": "error"}
        kind = facts["kind"]
        if kind in fallbacks.FIXED or kind in ("blocked", "unknown_slot"):
            return {"reply": fill(fixed_text(kind, facts), facts, deps.config.tz)}
        if kind == "answer":
            return {"reply": facts.get("text") or fallbacks.FALLBACKS["answer"]}

        placeholder = required_placeholder(kind, facts)
        variant = variant_of(kind, facts)
        system = template.safe_substitute(
            kind=variant,
            reason=facts.get("reason") or "none",
            situation=fallbacks.SITUATIONS.get(variant) or fallbacks.SITUATIONS.get(kind, "Reply politely."),
            first_name=(state.get("candidate") or {}).get("first_name", "there"),
            placeholder=placeholder or "none",
        )
        try:
            message = structured(deps.llm, system, "Write the message now.", ReplyText,
                                 context={"placeholder": placeholder, "booked": kind == "booked"}).message
        except StructuredOutputError:
            deps.audit.record("llm_fallback", step="reply", kind=kind)
            name = variant if variant in fallbacks.FALLBACKS else kind
            message = fallbacks.fallback_for(name, facts.get("reason"), has_slots=bool(facts.get("slots")))
        return {"reply": fill(message, facts, deps.config.tz)}

    return reply
