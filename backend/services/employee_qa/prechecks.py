# Deterministic pre-checks run before any retrieval or LLM call: injection, personal records, sensitive topics
import re
import unicodedata

from security.quarantine import screen_untrusted

_F = re.IGNORECASE

INJECTION = [re.compile(p, _F) for p in (
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(rules?|instructions?|prompts?|guidelines|restrictions)\b",
    r"\b(system|developer)\s*(prompt|message|mode)\b",
    r"\b(list|show|reveal|print|dump)\b.{0,30}\b(hr[- ]only|confidential|restricted|hidden)\b",
    r"\b(list|show|reveal|print|dump)\b.{0,10}\b(all|every)\b.{0,20}\b(documents?|files?)\b",
    r"\byou\s+are\s+now\b|\bpretend\s+(to\s+be|you\s+are)\b|\bact\s+as\s+(an?\s+)?(admin|hr|system)\b",
    r"\bjailbreak\b",
    r"<\s*/?\s*(system|assistant|documents?|section|employee_question)\b",
    r"\b(ignore[rz]?|oublie[rz]?)\b.{0,40}\b(regles?|règles?|instructions?|consignes?)\b",
    r"(تجاهل|انس).{0,30}(التعليمات|القواعد)",
)]

# Someone else's records, or the asker's own personal records: the assistant can see neither.
PEOPLE = r"(?:colleague|manager|boss|teammate|coworker|co-worker|(?!Northwind\b)(?-i:[A-Z][a-z]+))"  # names: real capitals
PERSONAL = [re.compile(p, _F) for p in (
    rf"\b(salary|pay|wage|bonus|leave balance|sick days|leave days|performance review|rating|warning)\s+(of|for)\s+"
    rf"(my\s+)?{PEOPLE}\b",
    rf"\bhow (much|many)\b.{{0,40}}\b(does|did|has)\s+(my\s+)?{PEOPLE}\b.{{0,40}}"
    r"\b(earn|make|get paid|paid|have left|take|taken)\b",
    r"\b(my|colleague'?s?|manager'?s?|boss'?s?)\s+(own\s+)?(salary|payslip|pay slip|bonus|leave balance|"
    r"remaining (leave|days)|performance review|disciplinary record|personnel file|hr file)\b",
    r"\bhow many (leave |vacation |holiday |sick )?days (do i|have i) (have )?(left|remaining|taken|used)\b",
    r"\b(what is|what's|tell me) my (salary|pay|bonus|balance|rating)\b",
)]

SENSITIVE = [re.compile(p, _F) for p in (
    r"\bharass\w*", r"\bbull(y|ied|ying)\b", r"\bdiscriminat\w*", r"\bsexual\w*", r"\bassault\w*",
    r"\babus(e|ed|ive)\b", r"\bmental health\b", r"\bdepress\w*", r"\banxi\w*", r"\bburn ?out\b",
    r"\bpanic attacks?\b", r"\bsuicid\w*", r"\bself[- ]harm\b", r"\bunsafe at work\b", r"\bthreaten\w*",
)]


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def is_injection(text: str) -> bool:
    return any(p.search(text) for p in INJECTION)


def precheck(question: str) -> str | None:
    """'blocked' | 'sensitive' | 'refused_personal' | None, decided without the LLM. Injection wins."""
    text = normalise(question)
    if is_injection(text) or screen_untrusted(text, "employee_question").blocked:  # shared rules + local model
        return "blocked"
    if any(p.search(text) for p in SENSITIVE):
        return "sensitive"
    if any(p.search(text) for p in PERSONAL):
        return "refused_personal"
    return None
