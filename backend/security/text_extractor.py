# Safely extracts plain text from uploaded documents
"""Extracts only the text a human reader would see.

Text that is white, tiny, outside the page or marked hidden is dropped, because
it exists to influence a machine. The dropped lines are returned separately so
the caller can check them for injection and tell the reviewer.
"""
import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import Any

from security.file_validator import FileRejected, ValidatedFile
from security.sanitizer import clean_untrusted_text

MAX_TEXT_CHARS = 40_000
MIN_FONT_POINTS = 3.0
NEAR_WHITE = 0.95

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class ExtractedText:
    text: str
    hidden_removed: bool = False
    truncated: bool = False
    hidden_lines: tuple[str, ...] = ()


def extract_visible_text(file: ValidatedFile) -> ExtractedText:
    visible, hidden = _pdf_text(file.data) if file.kind == "pdf" else _docx_text(file.data)
    cleaned = clean_untrusted_text(visible, MAX_TEXT_CHARS)
    hidden_text = clean_untrusted_text("\n".join(hidden), MAX_TEXT_CHARS).text
    hidden_lines = tuple(line.strip() for line in hidden_text.splitlines() if line.strip())
    return ExtractedText(cleaned.text, cleaned.hidden_removed or bool(hidden_lines), cleaned.truncated, hidden_lines)


def _luminance(color: Any) -> float:
    """Brightness of a PDF fill colour from 0 to 1. Unknown colour spaces count as dark, meaning visible."""
    values = color if isinstance(color, (tuple, list)) else (color,)
    if not all(isinstance(v, (int, float)) for v in values):
        return 0.0
    if len(values) == 1:
        return float(values[0])
    if len(values) == 3:
        r, g, b = values
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    if len(values) == 4:
        c, m, y, k = values
        r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    return 0.0


def _char_hidden(char: dict[str, Any], page: Any) -> bool:
    color = char.get("non_stroking_color")
    if color is not None and _luminance(color) >= NEAR_WHITE:
        return True
    if char.get("size", 0) < MIN_FONT_POINTS:
        return True
    x0, top, x1, bottom = page.bbox
    return char["x1"] <= x0 or char["x0"] >= x1 or char["bottom"] <= top or char["top"] >= bottom


def _pdf_text(data: bytes) -> tuple[str, list[str]]:
    import pdfplumber

    visible: list[str] = []
    hidden: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                # Off-page characters must be judged here: extract_text only sees the filtered objects.
                hidden_chars = [c for c in page.chars if _char_hidden(c, page)]
                keep = {id(c) for c in hidden_chars}
                if hidden_chars:
                    # Read in drawing order, because off-page text would not fit the page's line layout.
                    hidden.append("".join(c["text"] for c in hidden_chars))
                shown = page.filter(lambda o: o.get("object_type") != "char" or id(o) not in keep)
                visible.append(shown.extract_text() or "")
    except Exception:
        raise FileRejected("unreadable_pdf") from None
    return "\n".join(visible), hidden


def _switched_on(element: ET.Element | None) -> bool:
    return element is not None and element.get(f"{_W}val", "true").lower() not in {"false", "0", "off"}


def _run_hidden(run: ET.Element) -> bool:
    props = run.find(f"{_W}rPr")
    if props is None:
        return False
    if _switched_on(props.find(f"{_W}vanish")) or _switched_on(props.find(f"{_W}specVanish")):
        return True
    color = props.find(f"{_W}color")
    value = (color.get(f"{_W}val", "") if color is not None else "").lower()
    if len(value) == 6 and value != "auto":
        try:
            rgb = tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
        except ValueError:
            rgb = None
        if rgb and _luminance(rgb) >= NEAR_WHITE:
            return True
    size = props.find(f"{_W}sz")  # in half-points
    try:
        return size is not None and int(size.get(f"{_W}val", "24")) < MIN_FONT_POINTS * 2
    except ValueError:
        return False


def _own_runs(element: ET.Element) -> list[ET.Element]:
    """A paragraph's runs, leaving out nested paragraphs (text boxes), which are visited on their own."""
    runs: list[ET.Element] = []
    for child in element:
        if child.tag == f"{_W}r":
            runs.append(child)
        elif child.tag != f"{_W}p":
            runs.extend(_own_runs(child))
    return runs


def _run_text(run: ET.Element) -> str:
    parts: list[str] = []
    for child in run:
        if child.tag == f"{_W}t":
            parts.append(child.text or "")
        elif child.tag == f"{_W}tab":
            parts.append("\t")
        elif child.tag == f"{_W}br":
            parts.append("\n")
    return "".join(parts)


def _docx_text(data: bytes) -> tuple[str, list[str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise FileRejected("unreadable_docx") from None
    # A Word document never needs a DTD, and entity definitions are how XML bombs work.
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise FileRejected("unreadable_docx")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise FileRejected("unreadable_docx") from None

    visible: list[str] = []
    hidden: list[str] = []
    for paragraph in root.iter(f"{_W}p"):
        shown, removed = [], []
        for run in _own_runs(paragraph):
            (removed if _run_hidden(run) else shown).append(_run_text(run))
        visible.append("".join(shown))
        if any(part.strip() for part in removed):
            hidden.append("".join(removed))
    return "\n".join(visible), hidden
