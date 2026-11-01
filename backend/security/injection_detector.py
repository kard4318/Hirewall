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


# Used by find_injection_lines only, so is_suspicious keeps its behaviour for the drafter. Matched on folded text:
# lowercase, no accents or Arabic diacritics, alef forms unified, invisible characters removed.
_RESUME_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        # English: instructions aimed at whoever scores the resume
        r"\b(?:give|award|assign)\b.{0,30}\b(?:me|this candidate|this resume)\b.{0,30}\b(?:score|rating|marks?|10)\b",
        r"\bperfect score\b",
        r"\b(?:rank|score|mark|shortlist|select|hire)\b.{0,20}\b(?:me|this candidate|this resume)\b",
        r"\bmark\b.{0,20}\bas hired\b",
        r"\badmin mode\b|\bgod mode\b",
        # French
        r"\b(?:ignore[rz]?|oublie[rz]?|neglige[rz]?)\b.{0,40}\b(?:instructions?|consignes?|regles?)\b",
        r"\b(?:tu es|vous etes) (?:maintenant|desormais)\b",
        r"\b(?:classe[rz]?|mets|mettez|note[rz]?)[- ](?:moi|ce candidat|cette candidate)\b",
        r"\bmode (?:administrateur|admin|developpeur)\b",
        # Arabic
        r"(?:تجاهل|اهمل|انس|انسي)\S*.{0,30}(?:التعليمات|تعليمات|الاوامر|اوامر|القواعد|قواعد)",
        r"انت الان",
        r"(?:رتب|ضع|صنف)\S*.{0,30}(?:الاول|اولا|المرتبه الاولى)",
        r"(?:اعط|امنح)\S*.{0,30}(?:درجه|علامه|نقاط)",
    )
)
# Letters only, for "i g n o r e  a l l  i n s t r u c t i o n s" and similar spacing tricks.
_COMPACT = re.compile(r"(?:ignore|disregard|ignorez|oubliez)[a-z]{0,25}(?:instructions?|consignes?)|systemprompt")
_ARABIC_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})
_MAX_EXCERPT = 300


def _fold_line(line: str) -> str:
    normalized = unicodedata.normalize("NFKC", line)
    visible = "".join(char for char in normalized if unicodedata.category(char) not in {"Cf", "Co", "Cc"})
    decomposed = unicodedata.normalize("NFKD", visible)
    letters = "".join(char for char in decomposed if not unicodedata.combining(char) and char != "ـ")
    return re.sub(r"\s+", " ", letters.casefold().translate(_ARABIC_LETTERS)).strip()


def _line_matches(line: str) -> bool:
    if is_suspicious(line):
        return True
    folded = _fold_line(line)
    return any(p.search(folded) for p in _RESUME_PATTERNS) or bool(_COMPACT.search(re.sub(r"[^a-z]", "", folded)))


def injection_line_numbers(text: str) -> list[int]:
    """Indexes of the lines that look like instructions, including an instruction wrapped over two lines."""
    lines = text.splitlines()
    found = {index for index, line in enumerate(lines) if line.strip() and _line_matches(line)}
    for index in range(len(lines) - 1):
        first, second = lines[index], lines[index + 1]
        if first.strip() and second.strip() and index not in found and index + 1 not in found:
            if _line_matches(f"{first} {second}"):
                found.update((index, index + 1))
    return sorted(found)


def find_injection_lines(text: str) -> list[str]:
    """The offending lines, shortened, for a human reviewer. Display them as plain text."""
    lines = text.splitlines()
    return [lines[index].strip()[:_MAX_EXCERPT] for index in injection_line_numbers(text)]


def remove_injection_lines(text: str) -> str:
    """The text without its offending lines, for anything that feeds a model or an embedder."""
    drop = set(injection_line_numbers(text))
    return "\n".join(line for index, line in enumerate(text.splitlines()) if index not in drop)
