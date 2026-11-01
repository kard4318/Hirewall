# Restricts document access based on employee role, applied before retrieval, prompting, citation or answering
from services.employee_qa.models import Document, Section

READABLE = {"employee": {"everyone"}, "hr": {"everyone", "hr"}}


def readable_audiences(audience: str) -> set[str]:
    if audience not in READABLE:
        raise ValueError(f"unknown audience {audience!r}")
    return READABLE[audience]


def accessible_sections(documents: list[Document], audience: str) -> list[Section]:
    allowed = readable_audiences(audience)
    return [s for d in documents if d.audience in allowed for s in d.sections]


def forbidden_documents(documents: list[Document], audience: str) -> list[Document]:
    allowed = readable_audiences(audience)
    return [d for d in documents if d.audience not in allowed]
