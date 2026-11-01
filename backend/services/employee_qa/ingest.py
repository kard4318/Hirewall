# Parses the HR markdown corpus into numbered sections with stable ids, excluding superseded documents
import re
from pathlib import Path

from services.employee_qa.models import Document, Section
from services.employee_qa.prechecks import is_injection

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
HEADING = re.compile(r"^(#{2,3})\s+(\d+(?:\.\d+)?)\.?\s+(.+?)\s*$")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
NEUTRALIZED = "[instruction-like text removed]"
REQUIRED = ("doc_id", "title", "audience", "version", "effective_date", "topic")


def _front_matter(text: str, name: str) -> tuple[dict[str, str], str]:
    match = FRONT_MATTER.match(text)
    if not match:
        raise ValueError(f"{name}: missing front matter")
    meta = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        if key.strip():
            meta[key.strip()] = value.strip()
    missing = [k for k in REQUIRED if not meta.get(k)]
    if missing:
        raise ValueError(f"{name}: front matter needs {', '.join(missing)}")
    if meta["audience"] not in ("everyone", "hr"):
        raise ValueError(f"{name}: audience must be everyone or hr")
    return meta, text[match.end():]


def neutralize(text: str) -> tuple[str, int]:
    """Documents are data: replace sentences that read like instructions to an AI (defence in depth)."""
    kept, removed = [], 0
    for sentence in SENTENCE.split(text):
        if is_injection(sentence):
            kept.append(NEUTRALIZED)
            removed += 1
        else:
            kept.append(sentence)
    return " ".join(kept), removed


def parse_document(path: Path) -> Document:
    meta, body = _front_matter(path.read_text(encoding="utf-8"), path.name)
    body = HTML_COMMENT.sub("", body)
    sections: list[Section] = []
    removed_total = 0
    parent = ""
    current: tuple[str, str, str] | None = None  # (number, heading, parent heading)
    lines: list[str] = []

    def flush() -> None:
        nonlocal removed_total
        text = " ".join(" ".join(lines).split())
        if current is None or not text:
            return
        text, removed = neutralize(text)
        removed_total += removed
        number, heading, owner = current
        sections.append(Section(f"{meta['doc_id']}#{number}", meta["doc_id"], meta["title"], number, heading,
                                owner, text, meta["audience"], meta["version"], meta["topic"]))

    for line in body.splitlines():
        match = HEADING.match(line)
        if match:
            flush()
            level, number, heading = match.groups()
            if len(level) == 2:
                parent, current = heading, (number, heading, "")
            else:
                current = (number, heading, parent)
            lines = []
        elif current is not None and not line.startswith("#"):
            lines.append(line.strip())
    flush()

    supersedes = tuple(s.strip() for s in meta.get("supersedes", "").split(",") if s.strip())
    return Document(meta["doc_id"], meta["title"], meta["audience"], meta["version"], meta["effective_date"],
                    meta["topic"], supersedes, meta.get("status", "active"), tuple(sections), removed_total)


def load_corpus(docs_dir: Path) -> tuple[list[Document], list[str]]:
    """(active documents, excluded doc ids). Superseded documents never reach retrieval, prompts or answers."""
    paths = [p for p in sorted(docs_dir.rglob("*.md")) if "eval" not in p.relative_to(docs_dir).parts]
    docs = [parse_document(p) for p in paths]
    ids = [d.doc_id for d in docs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate doc_id in the corpus")
    superseded = {s for d in docs for s in d.supersedes} | {d.doc_id for d in docs if d.status == "superseded"}
    return [d for d in docs if d.doc_id not in superseded], sorted(superseded & set(ids))
