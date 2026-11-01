# Sanitizes untrusted text before it reaches the LLM

import re
import secrets
import unicodedata
from dataclasses import dataclass
from email.utils import getaddresses
from html.parser import HTMLParser

HTML_TAG_RE = re.compile(r"</?[a-zA-Z!][^>]*>")
_HIDDEN_STYLE_RE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0"
    r"|color\s*:\s*(?:white|#fff\b|#ffffff\b|transparent)",
    re.I,
)
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_BLOCK_TAGS = {"br", "p", "div", "li", "tr", "table", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
_SKIP_TAGS = {"script", "style", "head", "title", "template", "noscript"}


@dataclass(frozen=True)
class CleanText:
    text: str
    hidden_removed: bool = False
    truncated: bool = False


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        is_void = tag in _VOID_TAGS
        if self._skip_depth:
            self._skip_depth += 0 if is_void else 1
            return
        attributes = dict(attrs)
        hides = "hidden" in attributes or _HIDDEN_STYLE_RE.search(attributes.get("style") or "")
        if tag in _SKIP_TAGS or hides:
            self.hidden = True
            self._skip_depth = 0 if is_void else 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            self._skip_depth -= 0 if tag in _VOID_TAGS else 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            self.hidden = self.hidden or bool(data.strip())
        else:
            self.parts.append(data)

    def handle_comment(self, data: str) -> None:
        self.hidden = self.hidden or bool(data.strip())


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def clean_untrusted_text(raw: str, max_chars: int) -> CleanText:
    """Remove hidden content and invisible characters, and convert HTML to plain text."""
    text = normalize_newlines(unicodedata.normalize("NFKC", raw))
    kept: list[str] = []
    hidden = False
    for char in text:
        category = unicodedata.category(char)
        if char in "\n\t":
            kept.append(char)
        elif category in {"Zl", "Zp"}:
            kept.append("\n")
        elif category in {"Cc", "Cf", "Co", "Cs", "Cn"}:
            hidden = True
        else:
            kept.append(char)
    text = "".join(kept)

    if HTML_TAG_RE.search(text):
        parser = _VisibleText()
        parser.feed(text)
        parser.close()
        hidden = hidden or parser.hidden
        text = "".join(parser.parts)

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    truncated = len(text) > max_chars
    return CleanText(text[:max_chars], hidden, truncated)


def clean_single_line(raw: str, max_chars: int) -> CleanText:
    cleaned = clean_untrusted_text(raw, max_chars)
    return CleanText(" ".join(cleaned.text.split()), cleaned.hidden_removed, cleaned.truncated)


def normalize_address(raw: str) -> str | None:
    """Return one lowercase address, or None if the value is not exactly one address."""
    if "\r" in raw or "\n" in raw:
        return None
    parsed = getaddresses([raw])
    if len(parsed) != 1:
        return None
    address = parsed[0][1].strip().lower()
    return address if address.count("@") == 1 and " " not in address else None


def new_boundary() -> str:
    """Return a random marker for untrusted text, so that text cannot guess it and close the block early."""
    return f"UNTRUSTED_{secrets.token_hex(16)}"


def remove_boundary(text: str, boundary: str) -> str:
    while boundary in text:
        text = text.replace(boundary, "")
    return text
