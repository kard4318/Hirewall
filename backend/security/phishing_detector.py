# Detects phishing and social engineering in inbound email from concrete warning signs

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["phishing", "suspicious", "clean"]

PHISHING_SCORE = 4
SUSPICIOUS_SCORE = 2

_SENSITIVE_DATA = (
    r"bank (?:details|account)|passports?(?: copy)?|national id|social security|dates? of birth|tax forms?"
    r"|employee records|staff list|list of (?:all )?employees|salar(?:y|ies) of|home addresses"
    r"|every candidate|all candidates|all employees?|copy of your id"
)

# Each signal counts once: (name, weight, patterns).
_SIGNALS: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    (
        "credential_request",
        3,
        (
            r"(?:verify|confirm|validate|re-validate|update|secure)\s+(?:your\s+|access\s+)?"
            r"(?:identity|account|password|login|credentials)",
            r"(?:enter|provide|reply with|send)\b[^.?!]{0,50}\b(?:password|username|login|credentials)\b",
            r"\b(?:sign|log)(?:ging)?[- ]?in\b[^.?!]{0,50}"
            r"(?:to (?:view|see|read|download|keep|access)|with your|here|at http)",
            r"\b(?:access credentials|work login|password expires)\b",
            r"mot de passe",
        ),
    ),
    (
        "dangerous_attachment",
        4,
        (
            r"\.(?:exe|scr|bat|cmd|js|vbs|docm|xlsm|zip|rar|iso)\b",
            r"enable (?:macros|content|editing)",
            r"password[- ]protected",
            r"allow it to run",
        ),
    ),
    (
        "payment_request",
        3,
        (
            r"gift cards?",
            r"\bwire\b",
            r"(?:processing|registration|customs|release) fee",
            r"(?:bank|remittance|payment) details[^.?!]{0,20}(?:changed|updated)",
            r"updated our (?:bank|remittance|payment)",
            r"direct deposit",
            r"(?:salary|payroll)[^.?!]{0,60}(?:new account|new bank|account number)",
            r"(?:new account|new bank)[^.?!]{0,60}(?:salary|payroll)",
            r"(?:credit )?card number|update your credit card|\bPIN\b",
        ),
    ),
    (
        "sensitive_data_request",
        3,
        (rf"\b(?:send|forward|give|share|provide|confirm|need)\b[^.?!]{{0,80}}\b(?:{_SENSITIVE_DATA})\b",),
    ),
    (
        "too_good_to_be_true",
        3,
        (
            r"you have (?:won|been chosen)",
            r"\bwinner\b",
            r"claim your",
            r"\$\s?\d[\d,]*\s*(?:a|per)\s+(?:day|week)",
            r"tax refund",
        ),
    ),
    (
        "authority_claim",
        2,
        (
            r"\b(?:this is|i am|i'm)\s+(?:the|a|your)?\s*(?:\w+\s+){0,2}"
            r"(?:ceo|cfo|cto|director|president|chairman|board member|auditors?)\b",
            r"\bwe are your (?:\w+ )?auditors\b",
        ),
    ),
    (
        "secrecy_or_unreachable",
        2,
        (
            r"keep (?:this|it) (?:confidential|between|quiet|secret)",
            r"between us",
            r"tell nobody",
            r"(?:do not|don't) (?:discuss|call|copy)",
            r"discreetly",
            r"reply (?:to me )?here only",
            r"(?:cannot|can't) (?:talk|take calls)",
            r"hard to reach",
        ),
    ),
    ("pretext", 2, (r"are you (?:at your desk|available)\?", r"quick favou?r")),
    (
        "lure",
        2,
        (
            r"click here",
            r"shared with you",
            r"awaiting your signature",
            r"new voicemail",
            r"unusual (?:sign-in|activity)",
            r"mailbox is (?:almost )?full",
        ),
    ),
    (
        "threat",
        1,
        (
            r"(?:will be|has been|sera) (?:deleted|suspended|locked|suspendu)",
            r"lock your account",
            r"lose your|avoid losing",
            r"legal action",
            r"will stop",
        ),
    ),
    (
        "urgency",
        1,
        (
            r"immediately",
            r"urgent",
            r"right now",
            r"within (?:\d+ hours?|the hour)",
            r"\bexpires?\b",
            r"close of business|end of day|tonight",
        ),
    ),
    ("link", 1, (r"https?://",)),
)
_COMPILED = tuple((name, weight, tuple(re.compile(p, re.I) for p in patterns)) for name, weight, patterns in _SIGNALS)


@dataclass(frozen=True)
class PhishingAssessment:
    verdict: Verdict
    score: int
    signals: tuple[str, ...]


def assess_phishing(text: str) -> PhishingAssessment:
    """Score one email's subject and body. The named signals tell a reviewer why it was flagged."""
    normalized = unicodedata.normalize("NFKC", text).replace("’", "'")
    visible = "".join(char for char in normalized if unicodedata.category(char) not in {"Cf", "Co"})
    signals = [name for name, _, patterns in _COMPILED if any(pattern.search(visible) for pattern in patterns)]
    weights = {name: weight for name, weight, _ in _COMPILED}
    score = sum(weights[name] for name in signals)
    verdict: Verdict = "phishing" if score >= PHISHING_SCORE else "suspicious" if score >= SUSPICIOUS_SCORE else "clean"
    return PhishingAssessment(verdict, score, tuple(signals))
