# Tiny rule-based stand-in for the LLM so the scheduling chat works offline (LLM_PROVIDER=fake)
import json
import re
from datetime import date, timedelta

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FULL_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
ORDINAL = re.compile(r"\b(1|2|3|first|second|third|last)\b")
YES = re.compile(r"^\s*(yes|yep|yeah|ok|okay|sure|confirm|book it|perfect)\b")
NO = re.compile(r"^\s*(no|nope|none|neither)\b")


def demo_rules(system: str, user: str) -> str:
    if system.startswith("TASK: understand"):
        return json.dumps(_understand(system, user))
    if system.startswith("TASK: reply"):
        from services.scheduler.conversation.fallbacks import fallback_for

        kind = re.search(r"^Kind: (\S+)", system, re.M)
        reason = re.search(r"^Reason: (\S+)", system, re.M)
        has_slots = "Required placeholder: {{SLOTS}}" in system
        message = fallback_for(kind.group(1) if kind else "error", reason.group(1) if reason else None, has_slots)
        return json.dumps({"message": message})
    if system.startswith("TASK: answer"):
        return json.dumps({"answer": "The interview lasts about 45 minutes by video call. "
                                     "For anything else, I'll pass your question to HR."})
    return "{}"


def _message(user: str) -> str:
    match = re.search(r"<candidate_message>\s*(.*?)\s*</candidate_message>", user, re.S)
    return (match.group(1) if match else user).lower()


def _weekdays_in(text: str) -> list[str]:
    return [WEEKDAYS[i] for i, name in enumerate(FULL_NAMES) if re.search(rf"\b({name}|{WEEKDAYS[i]})\b", text)]


def _understand(system: str, user: str) -> dict:
    text = _message(user)
    has_offers = re.search(r"offered in this conversation: (?!none)", system) is not None
    today_match = re.search(r"Today is (\d{4}-\d{2}-\d{2})", system)
    today = date.fromisoformat(today_match.group(1)) if today_match else date.today()
    days = _weekdays_in(text)

    if YES.search(text):
        return {"intent": "confirm"}
    if NO.search(text):
        return {"intent": "decline"}
    if has_offers and re.search(r"\b(other|another|more|different|else)\b", text):
        return {"intent": "ask_slots", "more_options": True}
    ordinal = ORDINAL.search(text)
    if has_offers and ordinal and not re.search(r"\b(after|before)\b", text):
        return {"intent": "choose_slot", "slot_ref": ordinal.group(1)}
    if has_offers and len(days) == 1 and re.search(r"\b(one|actually|take|that)\b", text):
        return {"intent": "choose_slot", "slot_ref": days[0]}

    preference: dict = {}
    if "next week" in text:
        monday = today + timedelta(days=7 - today.weekday())
        preference.update(dates_from=monday.isoformat(), dates_to=(monday + timedelta(days=4)).isoformat())
    if days:
        preference["weekdays"] = [d for d in WEEKDAYS[:5] if d not in days] if "except" in text else days
    for word, key in (("after", "earliest"), ("before", "latest")):
        hour = re.search(rf"\b{word}\s+(\d{{1,2}})\s*(am|pm)?", text)
        if hour:
            value = int(hour.group(1)) % 12 + (12 if hour.group(2) == "pm" or (not hour.group(2) and int(hour.group(1)) < 8) else 0)
            preference[key] = f"{value:02d}:00"
    asks_for_slots = re.search(r"\b(slot|slots|time|times|available|availability|when|free|book)\b", text)
    if preference or asks_for_slots:
        return {"intent": "ask_slots", "preference": preference}
    if "?" in text or re.match(r"(how|what|who|do|does|is|can|should|will)\b", text):
        return {"intent": "question"}
    return {"intent": "other"}
