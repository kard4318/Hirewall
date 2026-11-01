# Validates LLM outputs before they are used: invisible characters, prompt leaks, unexpected links and emails
import re

from core.llm.canary import leaked

INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁩﻿­]")
CONTACT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|https?://\S+|www\.\S+", re.IGNORECASE)
# Any canary at all: callers that do not know this request's canary still catch one copied from a prompt.
CANARY = re.compile(r"HWCANARY-?[0-9a-f]{16}", re.IGNORECASE)
PROMPT_LEAK = re.compile(r"\b(?:TASK:|system prompt|BEGIN_UNTRUSTED|END_UNTRUSTED|<\s*/?\s*(?:documents|section|"
                         r"employee_question|candidate_message)\b)", re.IGNORECASE)


def output_problems(
    text: str, allowed_contacts: set[str] | None = None, max_chars: int = 4000, canary: str | None = None
) -> list[str]:
    """Reasons the model output must not be used; empty when it is acceptable.

    `allowed_contacts`: emails/URLs that appear in trusted context and may therefore be repeated.
    `canary`: the marker that was in the system prompt (core.llm.canary); seeing it means the prompt leaked.
    """
    problems = []
    if canary and leaked(text, canary) or CANARY.search(text):
        problems.append("canary_leak")
    if len(text) > max_chars:
        problems.append("too_long")
    if INVISIBLE.search(text):
        problems.append("invisible_characters")
    if PROMPT_LEAK.search(text):
        problems.append("prompt_leak")
    allowed = {c.lower() for c in (allowed_contacts or set())}
    if any(c.lower().rstrip(".,;)") not in allowed for c in CONTACT.findall(text)):
        problems.append("unexpected_contact")
    return problems
