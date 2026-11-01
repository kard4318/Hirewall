# Deterministic checks on untrusted input and on drafted output

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from security.sanitizer import HTML_TAG_RE

from .config import DrafterConfig
from .models import Claim, DraftContext, ReasonCode

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}  # fmt: skip
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_FILE_EXTENSIONS = {"pdf", "doc", "docx", "txt", "png", "jpg", "jpeg", "odt", "rtf"}

_SCHEME_URL_RE = re.compile(r"\b(?:[a-z][a-z0-9+.\-]*://|(?:mailto|javascript|data|tel|sms):)\S+", re.I)
_EMAIL_RE = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", re.I)
_OBFUSCATED_URL_RE = re.compile(
    r"\b[a-z0-9\-]+\s*(?:\[\.\]|\(\.\)|\bdot\b)\s*(?:com|net|org|io|co|info|biz|xyz)\b", re.I
)
_BARE_URL_RE = re.compile(r"\b(?:[a-z0-9\-]+\.)+[a-z]{2,24}\b(?:/\S*)?", re.I)
_MONEY_RE = re.compile(
    r"[$€£¥]\s?\d[\d,.]*\s?k?\b|\b\d[\d,.]*\s?k?\s?(?:usd|eur|gbp|tnd|cad|dollars?|euros?|pounds?|dinars?)\b", re.I
)
# The time and offset are part of the match, so an offset such as +00:00 is not read as a separate time.
_ISO_DATE_RE = re.compile(
    r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?(?!\d)"
)
_NUMERIC_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})(?!\d)")
_DAY_MONTH_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\b\.?(?:,?\s+(\d{{4}})\b)?", re.I)
_MONTH_DAY_RE = re.compile(rf"\b({_MONTH_RE})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}})\b)?", re.I)
_CLOCK_RE = re.compile(r"(?<![\d:])(\d{1,2})[:h](\d{2})(?::\d{2})?\s*([ap])?\.?(m)?\b\.?", re.I)
_MERIDIEM_RE = re.compile(r"(?<![\d:])(\d{1,2})\s*([ap])\.?m\b\.?", re.I)
_RELATIVE_DATE_RE = re.compile(
    r"\b(?:tomorrow|tonight|next (?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"|end of (?:the )?(?:day|week|month)|within (?:a|an|one|two|three|four|five|few|several) (?:\w+ )?"
    r"(?:hours?|days?|weeks?|months?))\b",
    re.I,
)
_PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d ().\-]{6,}\d(?!\w)")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\([^)]*\)")


@dataclass(frozen=True)
class DateFact:
    year: int | None
    month: int
    day: int

    def matches(self, other: "DateFact") -> bool:
        same_day = (self.month, self.day) == (other.month, other.day)
        return same_day and (self.year is None or other.year is None or self.year == other.year)


@dataclass
class Values:
    urls: set[str] = field(default_factory=set)
    emails: set[str] = field(default_factory=set)
    money: set[str] = field(default_factory=set)
    date_groups: list[tuple[DateFact, ...]] = field(default_factory=list)
    time_groups: list[tuple[int, ...]] = field(default_factory=list)
    weekdays: set[str] = field(default_factory=set)
    relative_dates: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    numbers: set[str] = field(default_factory=set)

    def merge(self, other: "Values") -> None:
        self.urls |= other.urls
        self.emails |= other.emails
        self.money |= other.money
        self.date_groups += other.date_groups
        self.time_groups += other.time_groups
        self.weekdays |= other.weekdays
        self.relative_dates |= other.relative_dates
        self.phones |= other.phones
        self.numbers |= other.numbers

    def add_datetime(self, value: date) -> None:
        self.date_groups.append((DateFact(value.year, value.month, value.day),))
        self.weekdays.add(_WEEKDAYS[value.weekday()])
        self.numbers.update({str(value.year), str(value.month), str(value.day)})
        if isinstance(value, datetime):
            self.time_groups.append((value.hour * 60 + value.minute,))

    def has_date(self, group: tuple[DateFact, ...]) -> bool:
        return any(fact.matches(known) for fact in group for known_group in self.date_groups for known in known_group)

    def has_time(self, group: tuple[int, ...]) -> bool:
        known = {minute for known_group in self.time_groups for minute in known_group}
        return any(minute in known for minute in group)


def _year(raw: str | None) -> int | None:
    if not raw:
        return None
    year = int(raw)
    return year + 2000 if year < 100 else year


def _valid_date(month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


def _collect(pattern: re.Pattern[str], text: str, handler: Any) -> str:
    def replace(match: re.Match[str]) -> str:
        return " " if handler(match) is not False else match.group(0)

    return pattern.sub(replace, text)


def _clock_group(hour: int, minute: int, meridiem: str | None) -> tuple[int, ...] | None:
    if minute > 59 or hour > 24:
        return None
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.lower() == "p" else 0)
        return (hour * 60 + minute,)
    if 1 <= hour < 12:
        return (hour * 60 + minute, (hour + 12) * 60 + minute)
    return (hour * 60 + minute,)


def extract_values(raw: str) -> Values:
    """Extract checkable values, masking each one so it is counted only once."""
    values = Values()
    text = raw.replace("’", "'")

    text = _collect(_SCHEME_URL_RE, text, lambda m: values.urls.add(m.group(0).lower()))
    text = _collect(_EMAIL_RE, text, lambda m: values.emails.add(m.group(0).lower()))
    text = _collect(_OBFUSCATED_URL_RE, text, lambda m: values.urls.add(m.group(0).lower()))

    def add_bare_url(match: re.Match[str]) -> bool | None:
        found = match.group(0).lower()
        if found.split("/")[0].rsplit(".", 1)[-1] in _FILE_EXTENSIONS:
            return False
        values.urls.add(found)
        return None

    text = _collect(_BARE_URL_RE, text, add_bare_url)
    text = _collect(_MONEY_RE, text, lambda m: values.money.add(re.sub(r"[^\dk]", "", m.group(0).lower())))

    def add_iso(match: re.Match[str]) -> bool | None:
        year, month, day = int(match[1]), int(match[2]), int(match[3])
        if not _valid_date(month, day):
            return False
        values.date_groups.append((DateFact(year, month, day),))
        if match[4] is not None:
            values.time_groups.append((int(match[4]) * 60 + int(match[5]),))
        return None

    def add_numeric(match: re.Match[str]) -> bool | None:
        first, second, year = int(match[1]), int(match[2]), _year(match[3])
        group = tuple(
            DateFact(year, month, day) for day, month in ((first, second), (second, first)) if _valid_date(month, day)
        )
        if not group:
            return False
        values.date_groups.append(group)
        return None

    def add_day_month(match: re.Match[str]) -> bool | None:
        day, month = int(match[1]), _MONTHS[match[2].lower()]
        if not _valid_date(month, day):
            return False
        values.date_groups.append((DateFact(_year(match[3]), month, day),))
        return None

    def add_month_day(match: re.Match[str]) -> bool | None:
        month, day = _MONTHS[match[1].lower()], int(match[2])
        if not _valid_date(month, day):
            return False
        values.date_groups.append((DateFact(_year(match[3]), month, day),))
        return None

    text = _collect(_ISO_DATE_RE, text, add_iso)
    text = _collect(_NUMERIC_DATE_RE, text, add_numeric)
    text = _collect(_DAY_MONTH_RE, text, add_day_month)
    text = _collect(_MONTH_DAY_RE, text, add_month_day)

    def add_clock(match: re.Match[str]) -> bool | None:
        meridiem = match[3] if match[4] else None
        group = _clock_group(int(match[1]), int(match[2]), meridiem)
        if group is None:
            return False
        values.time_groups.append(group)
        return None

    def add_meridiem(match: re.Match[str]) -> bool | None:
        group = _clock_group(int(match[1]), 0, match[2])
        if group is None:
            return False
        values.time_groups.append(group)
        return None

    text = _collect(_CLOCK_RE, text, add_clock)
    text = _collect(_MERIDIEM_RE, text, add_meridiem)

    values.relative_dates.update(m.group(0).lower() for m in _RELATIVE_DATE_RE.finditer(text))
    values.weekdays.update(w for w in _WEEKDAYS if re.search(rf"\b{w}\b", text, re.I))

    def add_phone(match: re.Match[str]) -> bool | None:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) < 8:
            return False
        values.phones.add(digits)
        return None

    text = _collect(_PHONE_RE, text, add_phone)
    values.numbers.update(found.replace(",", "") for found in _NUMBER_RE.findall(text))
    return values


def _flatten(value: Any) -> Iterator[Any]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _flatten(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten(item)
    elif value is not None:
        yield value


@dataclass
class Evidence:
    trusted: Values
    thread: Values


def build_evidence(context: DraftContext, *, recipient: str, feedback: str | None = None) -> Evidence:
    """Separate trusted facts from text the candidate could have written."""
    trusted = Values()
    trusted.emails.add(recipient.lower())
    for value in _flatten(context.trusted_view()):
        if isinstance(value, date):
            trusted.add_datetime(value)
        else:
            trusted.merge(extract_values(str(value)))
    if feedback:
        trusted.merge(extract_values(feedback))

    thread = Values()
    for message in context.thread:
        thread.merge(extract_values(f"{message.subject}\n{message.body}"))
    return Evidence(trusted, thread)


@dataclass
class CheckReport:
    blocking: list[ReasonCode] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def block(self, code: ReasonCode) -> None:
        if code not in self.blocking:
            self.blocking.append(code)

    def warn(self, warning: str) -> None:
        if warning not in self.warnings:
            self.warnings.append(warning)


def _domain_allowed(host: str, domains: Iterable[str]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _url_allowed(url: str, trusted: Values, config: DrafterConfig) -> bool:
    cleaned = url.rstrip(".,;:!?)'\"]")
    if cleaned in trusted.urls or url in trusted.urls:
        return True
    if not cleaned.startswith("https://"):
        return False
    try:
        host = urlsplit(cleaned).hostname
    except ValueError:
        return False
    return bool(host) and _domain_allowed(host, config.allowed_link_domains)


def check_format(subject: str, body: str, config: DrafterConfig) -> list[ReasonCode]:
    """Return a block when text cannot be sent safely, even after human approval."""
    has_controls = any(
        unicodedata.category(char) in {"Cc", "Cf", "Co", "Cs", "Cn"} and char not in "\n\t" for char in body
    ) or any(unicodedata.category(char) in {"Cc", "Cf", "Co", "Cs", "Cn"} for char in subject)
    invalid = (
        not subject.strip()
        or not body.strip()
        or len(subject) > config.max_subject_chars
        or len(body) > config.max_body_chars
        or has_controls
        or bool(HTML_TAG_RE.search(body) or HTML_TAG_RE.search(subject))
        or bool(_MARKDOWN_LINK_RE.search(body))
    )
    return [ReasonCode.FORMAT_INVALID] if invalid else []


def _check_values(text: str, evidence: Evidence, config: DrafterConfig, report: CheckReport) -> None:
    found = extract_values(text)
    trusted, thread = evidence.trusted, evidence.thread

    # URLs, email addresses, and amounts must not be accepted from the candidate's own text.
    if any(not _url_allowed(url, trusted, config) for url in found.urls):
        report.block(ReasonCode.UNSUPPORTED_URL)
    for email in found.emails:
        domain = email.rsplit("@", 1)[-1]
        if email not in trusted.emails and not _domain_allowed(domain, config.allowed_email_domains):
            report.block(ReasonCode.UNSUPPORTED_EMAIL)
    if found.money - trusted.money:
        report.block(ReasonCode.UNSUPPORTED_AMOUNT)

    for group in found.date_groups:
        if not trusted.has_date(group):
            if thread.has_date(group):
                report.warn("date_from_candidate_email")
            else:
                report.block(ReasonCode.UNSUPPORTED_DATE)
    for group in found.time_groups:
        if not trusted.has_time(group):
            if thread.has_time(group):
                report.warn("time_from_candidate_email")
            else:
                report.block(ReasonCode.UNSUPPORTED_DATE)
    for weekday in found.weekdays - trusted.weekdays:
        if weekday in thread.weekdays:
            report.warn("date_from_candidate_email")
        else:
            report.block(ReasonCode.UNSUPPORTED_DATE)
    relative_dates = found.relative_dates - trusted.relative_dates
    if relative_dates and relative_dates <= thread.relative_dates:
        report.warn("date_from_candidate_email")
    elif relative_dates:
        report.block(ReasonCode.UNSUPPORTED_DATE)

    for phone in found.phones - trusted.phones:
        if phone in thread.phones:
            report.warn("phone_from_candidate_email")
        else:
            report.block(ReasonCode.UNSUPPORTED_PHONE)
    for number in found.numbers - trusted.numbers:
        if number in thread.numbers:
            report.warn("number_from_candidate_email")
        else:
            report.block(ReasonCode.UNSUPPORTED_NUMBER)


def _matches_any(patterns: Iterable[str], text: str) -> bool:
    return any(re.search(rf"\b(?:{pattern})\b", text, re.I) for pattern in patterns)


def _check_decisions(
    text: str, context: DraftContext, language: str, config: DrafterConfig, report: CheckReport
) -> None:
    recorded = {decision.type for decision in context.decisions}
    normalized = text.replace("’", "'")
    for category, patterns in config.decision_phrases.get(language, {}).items():
        allowed = bool(recorded) if category == "outcome" else category in recorded
        if not allowed and _matches_any(patterns, normalized):
            report.block(ReasonCode.UNDECIDED_OUTCOME)


def _check_internal(text: str, language: str, config: DrafterConfig, report: CheckReport) -> None:
    if _matches_any(config.internal_phrases.get(language, ()), text):
        report.block(ReasonCode.INTERNAL_DATA)


def _resolve_path(view: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = view
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _value_supports(value: Any, claim_text: str) -> bool:
    if isinstance(value, dict):
        return any(_value_supports(item, claim_text) for item in value.values())
    if isinstance(value, list):
        return any(_value_supports(item, claim_text) for item in value)
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, date):
        known = Values()
        known.add_datetime(value)
        found = extract_values(claim_text)
        if not (found.date_groups or found.time_groups or found.weekdays):
            return False
        return (
            all(known.has_date(group) for group in found.date_groups)
            and all(known.has_time(group) for group in found.time_groups)
            and found.weekdays <= known.weekdays
        )
    tokens = _tokens(str(value))
    return bool(tokens) and tokens <= _tokens(claim_text)


def _value_mentioned(value: Any, body: str) -> bool:
    """Return True if the draft actually states the cited value, so a citation cannot sit beside a contradiction."""
    if isinstance(value, dict):
        return any(_value_mentioned(item, body) for item in value.values())
    if isinstance(value, list):
        return any(_value_mentioned(item, body) for item in value)
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, date):
        known = Values()
        known.add_datetime(value)
        return any(known.has_date(group) for group in extract_values(body).date_groups)
    tokens = {_stem(token) for token in _tokens(str(value))}
    return bool(tokens) and tokens <= {_stem(token) for token in _tokens(body)}


def _stem(token: str) -> str:
    """Let "moving" match "move", so a correct reply is not blocked for changing a word's ending."""
    return re.sub(r"(?:ing|ed|es|e|s)$", "", token) if len(token) >= 4 else token


def _check_claims(claims: list[Claim], intent: str, body: str, context: DraftContext, report: CheckReport) -> None:
    view = context.trusted_view()
    stated = 0
    for claim in claims:
        exists, value = _resolve_path(view, claim.source_field)
        if not exists or not _value_supports(value, claim.text):
            report.block(ReasonCode.CLAIM_UNSUPPORTED)
        elif _value_mentioned(value, body):
            stated += 1
        else:
            # A true fact the draft does not use is harmless, but the reviewer should not read it as a source.
            report.warn("claim_not_in_draft")
    # These replies report facts, so at least one cited fact must actually appear in the text.
    if intent in {"status_update", "scheduling", "request_info"} and not stated:
        report.block(ReasonCode.CLAIM_UNSUPPORTED)


def _states_wrong_stage(body: str, context: DraftContext) -> bool:
    """Catch a reply saying "under review" to someone advanced or rejected, whatever it cites."""
    return context.stage != "under_review" and bool(re.search(r"\bunder review\b", body, re.I))


def _says_missing_document_arrived(body: str, context: DraftContext, language: str, config: DrafterConfig) -> bool:
    received = config.received_phrases.get(language, ())
    negations = config.not_received_phrases.get(language, ())
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body.replace("’", "'")):
        words = _tokens(sentence)
        names_missing = any(_tokens(document) <= words for document in context.documents_missing)
        if names_missing and _matches_any(received, sentence) and not _matches_any(negations, sentence):
            return True
    return False


def base_language(language: str) -> str:
    return language.strip().lower().replace("_", "-").split("-")[0]


def check_text(
    subject: str, body: str, *, context: DraftContext, evidence: Evidence, language: str, config: DrafterConfig
) -> CheckReport:
    """Run every content check that does not depend on LLM metadata."""
    report = CheckReport()
    for code in check_format(subject, body, config):
        report.block(code)
    text = f"{subject}\n{body}"
    _check_values(text, evidence, config, report)
    _check_decisions(text, context, language, config, report)
    _check_internal(text, language, config, report)
    if context.documents_missing and (
        _matches_any(config.complete_phrases.get(language, ()), text.replace("’", "'"))
        or _says_missing_document_arrived(body, context, language, config)
    ):
        report.block(ReasonCode.CONTRADICTS_RECORD)
    if _states_wrong_stage(body, context):
        report.block(ReasonCode.CONTRADICTS_RECORD)
    if re.search(r"\b[a-z]+_[a-z_]+\b", body):
        report.warn("raw_field_value")
    # A warning rather than a block: the promise is harmless if the recruiter intends to keep it.
    if _matches_any(config.promise_phrases.get(language, ()), text.replace("’", "'")):
        report.warn("promise_to_confirm")
    return report


def check_draft(
    subject: str,
    body: str,
    *,
    claims: list[Claim],
    intent: str,
    context: DraftContext,
    evidence: Evidence,
    language: str,
    config: DrafterConfig,
) -> CheckReport:
    report = check_text(subject, body, context=context, evidence=evidence, language=language, config=config)
    _check_claims(claims, intent, body, context, report)
    return report
