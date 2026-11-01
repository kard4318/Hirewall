# Validates uploaded files (type, size, structure)
"""Checks an uploaded resume before any parser reads it.

Only PDF and DOCX are accepted, judged by their real signature rather than the
file name. Limits are checked on the raw bytes and the zip directory first, so a
crafted file is refused before it can use much memory or time.
"""
import io
import zipfile
from dataclasses import dataclass
from typing import Literal

MAX_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 10
MAX_DOCX_MEMBERS = 200
MAX_DOCX_UNCOMPRESSED = 20 * 1024 * 1024
MAX_DOCX_RATIO = 100

FileKind = Literal["pdf", "docx"]
_EXTENSIONS: dict[str, FileKind] = {".pdf": "pdf", ".docx": "docx"}


class FileRejected(Exception):
    """The file is refused. The message is a short reason code, safe to show and log."""


@dataclass(frozen=True)
class ValidatedFile:
    kind: FileKind
    data: bytes


def validate_upload(filename: str, data: bytes) -> ValidatedFile:
    """Return the file with its kind, or raise FileRejected(reason_code)."""
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
    return ValidatedFile(kind, data)


def _check_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF-"):
        raise FileRejected("bad_signature")
    if b"/Encrypt" in data:
        raise FileRejected("encrypted_pdf")
    import pdfplumber  # imported here so the DOCX path and the drafter never load it

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if getattr(pdf.doc, "encryption", None):
                raise FileRejected("encrypted_pdf")
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
