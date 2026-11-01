# Masks PII and filters bias-inducing attributes: regex-based, local, used before storing or scoring text
import re

PII_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?\b"),
    "card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "phone": re.compile(r"(?<!\w)(?:\+|00)?\d[\d\s().-]{7,}\d(?!\w)"),
    "url": re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE),
}
# Lines that state a protected attribute ("Age: 34", "Nationalité : ...", "Marital status - married").
PROTECTED = re.compile(
    r"^\s*(?:age|âge|date of birth|birth ?date|dob|date de naissance|gender|sex|sexe|genre|marital status|"
    r"situation (?:familiale|matrimoniale)|nationality|nationalité|religion|ethnicity|race|photo|picture|"
    r"place of birth|lieu de naissance|children|enfants|disability|handicap)\s*[:\-–]\s*.*$",
    re.IGNORECASE | re.MULTILINE,
)


def mask_pii(text: str) -> tuple[str, dict[str, int]]:
    """Replace personal data with [EMAIL], [PHONE]... and count what was masked."""
    counts: dict[str, int] = {}
    for name, pattern in PII_PATTERNS.items():
        text, n = pattern.subn(f"[{name.upper()}]", text)
        if n:
            counts[name] = n
    return text, counts


def strip_protected_attributes(text: str) -> tuple[str, int]:
    """Remove lines stating age, gender, nationality, religion, family status...: never relevant to screening."""
    cleaned, n = PROTECTED.subn("[removed: protected attribute]", text)
    return cleaned, n
