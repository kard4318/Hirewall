# Reads a CSV of candidates: each row names files uploaded with it, or holds the CV and cover letter as text
"""The CSV is untrusted. A cell that looks like a file name is only ever matched against the files uploaded in the
same request: nothing here opens a path on disk."""
import csv
import io
import re
from dataclasses import dataclass

from security.file_validator import MAX_BYTES

MAX_ROWS = 100
_FILE_NAME = re.compile(r"^[^\r\n]{1,255}\.(?:pdf|docx)$", re.IGNORECASE)
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}$")
_COLUMNS = {
    "name": {"name", "full_name", "fullname", "candidate", "candidate_name", "nom", "nom_complet"},
    "email": {"email", "e_mail", "mail", "courriel"},
    "cv": {"cv", "cv_file", "cv_text", "resume", "resume_file", "resume_text"},
    "cover_letter": {"cover_letter", "cover_letter_file", "cover_letter_text", "letter", "lettre", "lettre_de_motivation"},
}


class CsvRejected(Exception):
    """The CSV as a whole cannot be used. The message is a short reason code."""


@dataclass(frozen=True)
class Document:
    """Either a file name to find among the uploads, or the document's text."""
    file_name: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class CsvRow:
    name: str | None
    email: str | None
    cv: Document | None
    cover_letter: Document | None


def file_key(name: str) -> str:
    """Compare by base name only, ignoring case, so a path in a cell can never reach outside the upload."""
    return re.split(r"[\\/]", name.strip())[-1].casefold()


def _document(cell: str) -> Document | None:
    value = cell.strip()
    if not value:
        return None
    return Document(file_name=file_key(value)) if _FILE_NAME.match(value) else Document(text=value)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")  # Excel on Windows


def _column_key(header: str) -> str:
    return re.sub(r"[\s-]+", "_", header.strip().casefold())


def parse_candidates_csv(data: bytes) -> list[CsvRow]:
    if len(data) > MAX_BYTES:
        raise CsvRejected("csv_too_large")
    text = _decode(data)
    first_line = text.split("\n", 1)[0]
    delimiter = max(",;\t", key=first_line.count)  # French Excel uses semicolons
    try:
        table = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except csv.Error:
        raise CsvRejected("csv_unreadable") from None
    if not table:
        raise CsvRejected("csv_empty")

    positions: dict[str, int] = {}
    for position, header in enumerate(table[0]):
        key = _column_key(header)
        for column, names in _COLUMNS.items():
            if key in names:
                positions.setdefault(column, position)
    if "cv" not in positions:
        raise CsvRejected("csv_no_cv_column")

    rows = [row for row in table[1:] if any(cell.strip() for cell in row)]
    if not rows:
        raise CsvRejected("csv_empty")
    if len(rows) > MAX_ROWS:
        raise CsvRejected("csv_too_many_rows")

    def cell(row: list[str], column: str) -> str:
        position = positions.get(column)
        return row[position] if position is not None and position < len(row) else ""

    parsed = []
    for row in rows:
        email = cell(row, "email").strip()
        parsed.append(CsvRow(
            name=" ".join(cell(row, "name").split())[:200] or None,
            email=email if len(email) <= 254 and _EMAIL.match(email) else None,
            cv=_document(cell(row, "cv")),
            cover_letter=_document(cell(row, "cover_letter")),
        ))
    return parsed
