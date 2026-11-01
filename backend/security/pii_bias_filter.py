# Masks PII and filters bias-inducing attributes: regex-based, local, used before storing or scoring text
import re
from dataclasses import dataclass

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


# Splitting a resume into identity and job evidence. The screener only ever receives the evidence.
_HEADING = re.compile(
    r"^\s*(?:summary|profile|objective|about me|experience|work experience|employment|professional experience|"
    r"education|skills|technical skills|projects?|certifications?|languages|profil|resume|expériences?|"
    r"experiences?|expérience professionnelle|formations?|compétences?|competences?|projets?|langues|"
    r"الخبرة|الخبرات|التعليم|المهارات|المشاريع|الملخص)\s*:?\s*$",
    re.IGNORECASE,
)
_ADDRESS = re.compile(r"^\s*(?:address|adresse|location|العنوان)\s*[:\-–].*$", re.IGNORECASE | re.MULTILINE)
_ARABIC_PROTECTED = re.compile(
    r"^\s*(?:العمر|السن|الجنس|الجنسية|تاريخ الميلاد|مكان الميلاد|الديانة|الحالة الاجتماعية)\s*[:\-–].*$", re.MULTILINE
)
_PROFILE_LINK = re.compile(
    r"https?://\S+|www\.\S+|\b(?:linkedin\.com|github\.com|gitlab\.com|twitter\.com|x\.com)/\S+", re.IGNORECASE
)
_NOT_A_NAME = re.compile(
    r"\b(?:curriculum|vitae|cv|resume|résumé|developer|engineer|analyst|manager|consultant|designer|intern|"
    r"junior|senior|lead|développeur|ingénieur|analyste|stagiaire|architect|scientist|administrator)\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_ONLY_MASKS = re.compile(r"^[\s|,;:/•·\-–—]*(?:\[(?:EMAIL|PHONE|LINK|CANDIDATE)\][\s|,;:/•·\-–—]*)*$")
CANDIDATE_TOKEN = "[CANDIDATE]"


@dataclass(frozen=True)
class Identity:
    full_name: str | None = None
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    other: tuple[str, ...] = ()


def _is_phone(candidate: str) -> bool:
    """PII_PATTERNS['phone'] also matches date ranges such as "2019 - 2022", which the screener needs."""
    groups = re.findall(r"\d+", candidate)
    digits = sum(len(group) for group in groups)
    if not 8 <= digits <= 15:
        return False
    if candidate.lstrip().startswith(("+", "00")):
        return True
    return not any(_YEAR.match(group) for group in groups)


def _name_line(lines: list[str]) -> str | None:
    """The first header line shaped like a person's name. A heuristic: see Known limits in docs/security.md."""
    for line in lines:
        words = line.split()
        if not 2 <= len(words) <= 4 or _NOT_A_NAME.search(line):
            continue
        if all(word.replace("-", "").replace("'", "").isalpha() for word in words):
            return line.strip()
    return None


def _mask_name(text: str, full_name: str) -> str:
    tokens = sorted({t for t in re.split(r"[\s]+", full_name) if len(t) >= 2}, key=len, reverse=True)
    if not tokens:
        return text
    alternation = "|".join(re.escape(token) for token in tokens)
    return re.sub(rf"(?<!\w)(?:{alternation})(?!\w)", CANDIDATE_TOKEN, text, flags=re.IGNORECASE)


def split_identity(text: str, known_name: str | None = None) -> tuple[Identity, str]:
    """Separate who a person is from what they did: (identity, evidence text with identity removed)."""
    lines = text.splitlines()
    header: list[str] = []
    for line in lines[:12]:
        if _HEADING.match(line):
            break
        if line.strip():
            header.append(line)

    full_name = known_name or _name_line(header)
    emails = tuple(dict.fromkeys(PII_PATTERNS["email"].findall(text)))
    links = tuple(dict.fromkeys(_PROFILE_LINK.findall(text)))
    other = [m.group(0).strip() for p in (PROTECTED, _ARABIC_PROTECTED, _ADDRESS) for m in p.finditer(text)]

    evidence = PII_PATTERNS["email"].sub("[EMAIL]", text)
    evidence = _PROFILE_LINK.sub("[LINK]", evidence)
    evidence = PII_PATTERNS["iban"].sub("[IBAN]", evidence)
    phones: list[str] = []

    def mask_phone(match: re.Match[str]) -> str:
        if not _is_phone(match.group(0)):
            return match.group(0)
        phones.append(match.group(0).strip())
        return "[PHONE]"

    evidence = PII_PATTERNS["phone"].sub(mask_phone, evidence)
    for pattern in (PROTECTED, _ARABIC_PROTECTED, _ADDRESS):
        evidence = pattern.sub("", evidence)
    if full_name:
        evidence = _mask_name(evidence, full_name)
    kept = [line for line in evidence.splitlines() if not line.strip() or not _ONLY_MASKS.match(line)]
    identity = Identity(full_name, emails, tuple(dict.fromkeys(phones)), links, tuple(other))
    return identity, re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def mask_identity(text: str, identity: Identity) -> str:
    """Remove one person's known details from a text, such as an excerpt shown to the reviewer."""
    for value in (*identity.emails, *identity.links, *identity.phones):
        text = text.replace(value, "[REMOVED]")
    return _mask_name(text, identity.full_name) if identity.full_name else text
