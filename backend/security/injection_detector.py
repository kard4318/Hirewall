# Detects prompt-injection attempts in untrusted input

import re
import unicodedata

_ACTIONS = r"(?:you|ignore|send|reveal|show|tell|copy|forward|always|never|do)"
_MARKERS = r"\[/?(?:inst|system)\]|<\|?/?(?:im_start|im_end|system)\|?>|(?:BEGIN_|END_)?UNTRUSTED_[0-9a-f]+\b"
_ROLE_CHANGE = r"\byou are now\b|\bact as (?:an?|the) (?:admin|system|developer|recruiter|hr)\b|\bfrom now on,? you\b"
_REVEAL = (
    r"\b(?:reveal|show|print|repeat|leak)\b.{0,30}\b(?:system prompt|your instructions|your rules|internal notes)\b"
)
_RANKING = (
    r"\b(?:rank|score|mark|shortlist)\b.{0,30}\b(?:me|this candidate)\b.{0,30}\b(?:first|highest|top|hired|selected)\b"
)
_RECIPIENT = (
    r"\b(?:copy|cc|bcc|forward)\b.{0,40}[\w.+-]+@[\w-]+\.[\w.-]+.{0,20}\b(?:on|in|to) (?:your|the) (?:reply|response)\b"
)

# A signal only. Other defenses must still hold when an attack avoids these patterns.
_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,40}\b(?:instructions?|rules?|prompts?|guidelines?)\b",
        r"\b(?:new|updated|real|actual) (?:instructions?|system prompt|policy from)\b",
        _REVEAL,
        _ROLE_CHANGE,
        rf"(?:^|\n)\s*(?:system|assistant|developer)\s*:\s*{_ACTIONS}\b",
        _MARKERS,
        r"\b(?:developer|admin|debug|jailbreak) mode\b|\bjailbreak\b|\bprompt injection\b",
        r"\b(?:tell|inform|confirm to) me\b.{0,30}\b(?:hired|selected|accepted|got the job)\b",
        _RANKING,
        _RECIPIENT,
        r"\bignore[rz]?\b.{0,40}\b(?:instructions|consignes|règles)\b",
        r"\boublie[rz]?\b.{0,40}\b(?:instructions|consignes|règles)\b",
    )
)


def is_suspicious(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text)
    visible = "".join(char for char in normalized if unicodedata.category(char) not in {"Cf", "Co"})
    return any(pattern.search(visible) for pattern in _PATTERNS)
