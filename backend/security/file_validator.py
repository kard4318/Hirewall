# Validates uploaded files (type, size, structure)
"""Checks an uploaded resume before any parser reads it.

Only PDF and DOCX are accepted, judged by their real signature rather than the
file name. Limits are checked on the raw bytes and the zip directory first, so a
crafted file is refused before it can use much memory or time.

Active content is refused: PDF scripts, automatic actions, launch actions, attached
files, XFA forms and rich media; DOCX macros, embedded objects and external links
other than ordinary hyperlinks. With CLAMAV_ENABLED, files are also scanned.
"""
import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any, Literal

from security.malware_scan import ScanUnavailable, scanner_from_env

MAX_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 10
MAX_DOCX_MEMBERS = 200
MAX_DOCX_UNCOMPRESSED = 20 * 1024 * 1024
MAX_DOCX_RATIO = 100

# PDF names that run code, act on open, start programs or carry other files. /AA is "additional actions".
ACTIVE_PDF_NAMES = frozenset({"JavaScript", "JS", "OpenAction", "AA", "Launch", "EmbeddedFiles", "XFA", "RichMedia"})
MAX_PDF_OBJECTS = 20_000
_PDF_NAME = re.compile(rb"/((?:[A-Za-z0-9_.+-]|#[0-9A-Fa-f]{2})+)")
_STREAMS = re.compile(rb"(?<![A-Za-z])stream\r?\n.*?endstream", re.DOTALL)
_HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"

FileKind = Literal["pdf", "docx"]
_EXTENSIONS: dict[str, FileKind] = {".pdf": "pdf", ".docx": "docx"}


class FileRejected(Exception):
    """The file is refused. The message is a short reason code, safe to show and log."""


@dataclass(frozen=True)
class ValidatedFile:
    kind: FileKind
    data: bytes


def validate_upload(filename: str, data: bytes, scanner: Any = None) -> ValidatedFile:
    """Return the file with its kind, or raise FileRejected(reason_code).

    `scanner` defaults to ClamAV from the environment (off unless CLAMAV_ENABLED=true).
    """
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = _EXTENSIONS.get(extension)
    if kind is None:
        raise FileRejected("unsupported_type")
    if not data:
        raise FileRejected("empty_file")
    if len(data) > MAX_BYTES:
        raise FileRejected("file_too_large")
    if kind == "pdf":
        _check_pdf(data)
    else:
        _check_docx(data)
    _scan(data, scanner if scanner is not None else scanner_from_env())
    return ValidatedFile(kind, data)


def _scan(data: bytes, scanner: Any) -> None:
    if not scanner:
        return
    try:
        infected = scanner.is_infected(data)
    except ScanUnavailable:
        raise FileRejected("scan_unavailable") from None  # fail closed: an unscanned file never passes
    if infected:
        raise FileRejected("malware_found")


def raw_active_names(data: bytes) -> set[str]:
    """PDF names in the raw bytes, with #xx escapes decoded, so /J#61vaScript is found as /JavaScript.

    Stream contents are skipped: compressed images are random bytes and could hold "/JS" by chance. Names inside
    compressed object streams are found by parsed_active_names instead.
    """
    found = set()
    for match in _PDF_NAME.finditer(_STREAMS.sub(b"stream endstream", data)):
        raw = match.group(1)
        name = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw).decode("latin-1")
        if name in ACTIVE_PDF_NAMES:
            found.add(name)
    return found


def parsed_active_names(doc: Any) -> set[str]:
    """Active names in the parsed objects, which also covers compressed object streams the raw scan cannot read."""
    from pdfminer.pdftypes import PDFObjRef, PDFStream, resolve1

    found: set[str] = set()
    seen: set[int] = set()

    def walk(value: Any, depth: int) -> None:
        if depth > 12:
            return
        if isinstance(value, PDFObjRef):
            if value.objid in seen or len(seen) > MAX_PDF_OBJECTS:
                return
            seen.add(value.objid)
            try:
                value = resolve1(value)
            except Exception:
                return
        if isinstance(value, PDFStream):
            value = value.attrs
        if isinstance(value, dict):
            for key, item in value.items():
                name = key.decode("latin-1") if isinstance(key, bytes) else str(key)
                if name in ACTIVE_PDF_NAMES:
                    found.add(name)
                walk(item, depth + 1)
            name = getattr(value.get("S"), "name", None)
            if name in ACTIVE_PDF_NAMES:
                found.add(name)
        elif isinstance(value, list):
            for item in value[:2000]:
                walk(item, depth + 1)

    walk(doc.catalog, 0)
    for xref in doc.xrefs:
        for objid in list(xref.get_objids())[:MAX_PDF_OBJECTS]:
            if objid in seen:
                continue
            seen.add(objid)
            try:
                walk(doc.getobj(objid), 1)
            except Exception:
                continue
    return found


def _check_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF-"):
        raise FileRejected("bad_signature")
    if b"/Encrypt" in data:
        raise FileRejected("encrypted_pdf")
    if raw_active_names(data):
        raise FileRejected("active_pdf_content")
    import pdfplumber  # imported here so the DOCX path and the drafter never load it

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if getattr(pdf.doc, "encryption", None):
                raise FileRejected("encrypted_pdf")
            if parsed_active_names(pdf.doc):
                raise FileRejected("active_pdf_content")
            pages = len(pdf.pages)
    except FileRejected:
        raise
    except Exception:
        raise FileRejected("unreadable_pdf") from None
    if pages == 0:
        raise FileRejected("unreadable_pdf")
    if pages > MAX_PDF_PAGES:
        raise FileRejected("too_many_pages")


def _check_docx(data: bytes) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise FileRejected("bad_signature")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
    except (zipfile.BadZipFile, ValueError):
        raise FileRejected("unreadable_docx") from None
    if len(members) > MAX_DOCX_MEMBERS:
        raise FileRejected("zip_bomb")
    total = 0
    for member in members:
        name = member.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            raise FileRejected("bad_archive_path")
        total += member.file_size
        if member.file_size > MAX_DOCX_RATIO * max(member.compress_size, 1) and member.file_size > 1024 * 1024:
            raise FileRejected("zip_bomb")
    if total > MAX_DOCX_UNCOMPRESSED:
        raise FileRejected("zip_bomb")
    if "word/document.xml" not in {m.filename for m in members}:
        raise FileRejected("unreadable_docx")
    _check_docx_active(data, members)


def _check_docx_active(data: bytes, members: list[zipfile.ZipInfo]) -> None:
    """Macros, embedded objects and remote templates or frames. Sizes were already checked above."""
    names = [member.filename.replace("\\", "/").lower() for member in members]
    if any(name.endswith("vbaproject.bin") or "/embeddings/" in f"/{name}" or name.startswith("word/activex/")
           for name in names):
        raise FileRejected("active_docx_content")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        types = archive.read("[Content_Types].xml") if "[content_types].xml" in names else b""
        if b"macroEnabled" in types or b"vbaProject" in types:
            raise FileRejected("active_docx_content")
        for member in members:
            if not member.filename.lower().endswith(".rels"):
                continue
            rels = archive.read(member).decode("utf-8", "replace")
            for relationship in re.findall(r"<Relationship\b[^>]*>", rels):
                external = re.search(r'TargetMode\s*=\s*"External"', relationship, re.IGNORECASE)
                # A plain hyperlink is only followed if a reader clicks it; anything else external is fetched on open.
                if external and f'Type="{_HYPERLINK}"' not in relationship:
                    raise FileRejected("active_docx_content")
