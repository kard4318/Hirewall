# Slot formatting and the reply validator that keeps dates/times out of LLM-written text
import re
from datetime import tzinfo

from services.scheduler.models import TimeSlot

SLOTS = "{{SLOTS}}"
SLOT = "{{SLOT}}"
PLACEHOLDER = re.compile(r"\{\{[^{}]*\}\}")

_WEEKDAYS = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun"
_MONTHS = (r"january|february|march|april|june|july|august|september|october|november|december"
           r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")  # "may" left out: too common as a verb
DATE_TIME = re.compile(
    r"\b\d{1,2}\s*[:h.]\s*\d{2}\b"           # 3:17, 10h30, 10.30
    r"|\b\d{1,2}\s*(?:am|pm|a\.m\.|p\.m\.)"  # 3pm, 10 a.m.
    r"|\b\d{4}-\d{1,2}-\d{1,2}\b"            # 2026-11-03
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"     # 3/11, 03/11/2026
    rf"|\b(?:{_WEEKDAYS}|{_MONTHS})\b"
    r"|\b(?:today|tonight|tomorrow|yesterday|noon|midnight|o'clock)\b",
    re.IGNORECASE,
)
LINK_OR_EMAIL = re.compile(r"https?://|www\.|@", re.IGNORECASE)
# Claims that something is already booked; only allowed in the actual booking confirmation.
BOOKING_CLAIM = re.compile(
    r"\b((?<!fully )booked|scheduled|confirmed|reserved|all set|is set|have set|r[ée]serv[ée]e?s?|confirm[ée]e?s?|planifi[ée]e?s?)\b",
    re.IGNORECASE,
)
# Fragments of our own prompts: their presence means the model is leaking its instructions.
PROMPT_LEAK = re.compile(r"TASK:|candidate_message|required placeholder|json schema|untrusted data|FAQ:", re.IGNORECASE)


def format_slot(slot: TimeSlot, tz: tzinfo) -> str:
    start, end = slot.start.astimezone(tz), slot.end.astimezone(tz)
    return f"{start:%a} {start.day} {start:%b}, {start:%H:%M}-{end:%H:%M}"


def format_slot_list(slots: list[TimeSlot], tz: tzinfo) -> str:
    return "\n" + "\n".join(f"{i}) {format_slot(s, tz)}" for i, s in enumerate(slots, start=1)) + "\n"


def reply_problems(text: str, required: str | None, max_chars: int = 600, booked: bool = False) -> str | None:
    """Why an LLM-written reply is unsafe, or None if it is acceptable."""
    if len(text) > max_chars:
        return "message too long"
    found = PLACEHOLDER.findall(text)
    if required and found.count(required) != 1:
        return f"must contain {required} exactly once"
    if any(p != required for p in found):
        return "contains an unexpected placeholder"
    rest = text.replace(required, " ") if required else text
    if DATE_TIME.search(rest):
        return "must not contain dates, times, weekdays or months; use the placeholder"
    if LINK_OR_EMAIL.search(rest):
        return "must not contain links or email addresses"
    if PROMPT_LEAK.search(rest):
        return "must not repeat the instructions"
    if not booked and BOOKING_CLAIM.search(rest):
        return "nothing is booked yet; do not say it is booked, scheduled or confirmed"
    return None
