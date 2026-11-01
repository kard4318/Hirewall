# Shared rule-based injection screen: multilingual patterns (EN/FR/AR), obfuscation folding, and the
# patterns of security.injection_detector, so every service applies the same rules
import re
import unicodedata

from security.injection_detector import is_suspicious as detector_flags

# Control, zero-width and bidi characters (keeps \t and \n).
INVISIBLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f­؜᠎​-‏‪-‮⁠-⁩﻿]")
# Common Cyrillic/Greek look-alikes used to dodge keyword filters.
CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "ɡ": "g", "ο": "o", "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "τ": "t", "ρ": "p",
})
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})
ARABIC_MARKS = re.compile(r"[ً-ٰٟـ]")  # harakat and tatweel
ARABIC_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})

_FLAGS = re.IGNORECASE | re.MULTILINE
PATTERNS = [re.compile(p, _FLAGS) for p in (
    # English
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instructions?|rules|prompts?|guidelines)\b",
    r"\bsystem\s*prompt\b",
    r"\bdeveloper\s+(mode|message)\b",
    r"\byou\s+are\s+now\b",
    r"\b(pretend|act)\s+(to\s+be|you\s+are|as)\b",
    r"\bjailbreak\b",
    r"\b(reveal|print|show|repeat|output)\b.{0,30}\b(your|the\s+system|hidden|initial|original)\s+(prompt|instructions)\b",
    # French (accents removed by folding)
    r"\b(ignore[rz]?|oublie[rz]?|neglige[rz]?)\b.{0,40}\b(instructions?|consignes?|regles?)\b",
    r"\bne\s+(tiens|tenez)\s+(pas|plus)\s+compte\b",
    r"\b(prompt|invite|message)\s+systeme\b",
    r"\b(tu\s+es|vous\s+etes)\s+desormais\b",
    r"\b(fais|faites)\s+comme\s+si\b|\bjoue[rz]?\s+le\s+role\b",
    r"\bmode\s+developpeur\b",
    # Arabic (diacritics removed, alef/ya/ta-marbuta folded)
    r"(تجاهل|اهمل|انس|انسي|تناس)\S*.{0,30}(التعليمات|تعليمات|الاوامر|اوامر|القواعد|قواعد)",
    r"(موجه|تعليمات|رساله)\s+النظام",
    r"تظاهر\s+ب",
    # Chat-template and role markers
    r"<\s*/?\s*(system|assistant|user|candidate_message|instructions?)\b",
    r"<\|\s*(im_start|im_end|system|assistant|endoftext)\s*\|>",
    r"\[\s*/?\s*(system|inst)\s*\]",
    r"^\s*(system|assistant|developer)\s*:",
    r"#{2,}\s*(system|instructions?)\b",
    r"```\s*(system|assistant)\b",
)]
# Letters-only view catches "i g n o r e", "s.y.s.t.e.m p.r.o.m.p.t" and similar spacing tricks.
COMPACT_PATTERNS = [re.compile(p) for p in (
    r"(ignore|disregard)[a-z]{0,25}instructions?",
    r"systemprompt",
    r"jailbreak",
    r"developermode",
)]


def clean_message(text: str) -> str:
    """What the rest of the graph sees: invisible characters removed, surrounding space trimmed."""
    return INVISIBLE.sub("", text).strip()


def fold(text: str) -> str:
    """Detection-only view: NFKC, no accents or Arabic diacritics, look-alikes mapped, lowercase."""
    text = INVISIBLE.sub("", unicodedata.normalize("NFKC", text))
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = ARABIC_MARKS.sub("", text.lower().translate(CONFUSABLES)).translate(ARABIC_FOLD)
    return re.sub(r"\s+", " ", text)


def rule_hits(text: str) -> list[str]:
    """Names of the rule sets that match (empty when none do). A signal only: other defences must still hold."""
    hits = []
    folded = fold(text)
    if any(p.search(variant) for variant in (folded, folded.translate(LEET)) for p in PATTERNS):
        hits.append("rules:multilingual")
    if any(p.search(re.sub(r"[^a-z]", "", folded.translate(LEET))) for p in COMPACT_PATTERNS):
        hits.append("rules:obfuscated")
    if detector_flags(text):
        hits.append("rules:detector")
    return hits


def screen(text: str) -> str | None:
    """Block reason for suspicious text, or None (rules only, no model)."""
    return "injection_suspected" if rule_hits(text) else None
