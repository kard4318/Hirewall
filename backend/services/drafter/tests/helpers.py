# Fakes and fictional data shared by the drafter tests

import json
from dataclasses import dataclass, field
from typing import Any

from services.drafter.models import DraftRequest
from services.drafter.node import DrafterDeps

SENDER = "sam.rivera@example.com"
SIGNATURE = "Nadia Karim\nRecruiting Team"
ACK_BODY = (
    "Hello Sam,\n\nThank you for your message. We have received it and will reply once the "
    f"recruiting team has reviewed it.\n\nKind regards,\n{SIGNATURE}"
)


class FakeLLM:
    """Returns scripted responses, and raises any scripted exception."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        response = self.responses[min(len(self.calls), len(self.responses)) - 1]
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def prompts(self) -> str:
        return "\n".join(f"{call['system']}\n{call['user']}" for call in self.calls)


class FakeDirectory:
    def __init__(self, *records: dict[str, Any]) -> None:
        self.records = records
        self.queries: list[str] = []

    def find_by_email(self, email: str) -> list[dict[str, Any]]:
        self.queries.append(email)
        return [record for record in self.records if record.get("email", "").lower() == email]


@dataclass
class FakeAudit:
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def record(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))


def make_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "candidate_id": "C-1042",
        "first_name": "Sam",
        "last_name": "Rivera",
        "email": SENDER,
        "job_title": "Data Analyst",
        "stage": "under_review",
        "documents_received": ["CV"],
        "documents_missing": ["Portfolio"],
        "interview": None,
        "decisions": [],
        "screening_score": 87,
        "ranking": 3,
        "internal_notes": "SECRET-NOTE-MARKER: strong but expensive",
        "date_of_birth": "1990-02-03",
    }
    record.update(overrides)
    return record


def make_request(body: str = "Hello, any news about my application?", **overrides: Any) -> DraftRequest:
    email = {
        "email_id": "msg-001",
        "thread_id": "thread-001",
        "from_address": f"Sam Rivera <{SENDER}>",
        "subject": "My application",
        "body": body,
        "received_at": "2026-11-02T09:00:00+00:00",
    }
    email.update(overrides.pop("email", {}))
    return DraftRequest.model_validate({"email": email, "recruiter_signature": SIGNATURE, **overrides})


def make_draft(**overrides: Any) -> dict[str, Any]:
    draft = {
        "intent": "ack",
        "language": "en",
        "subject": "Re: My application",
        "body": ACK_BODY,
        "claims": [],
        "needs_human_input": None,
        "risk_flags": [],
    }
    draft.update(overrides)
    return draft


def draft_json(**overrides: Any) -> str:
    return json.dumps(make_draft(**overrides))


def body_saying(sentence: str) -> str:
    return f"Hello Sam,\n\n{sentence}\n\nKind regards,\n{SIGNATURE}"


def make_deps(*responses: Any, record: dict[str, Any] | None = None, **overrides: Any) -> DrafterDeps:
    settings: dict[str, Any] = {
        "llm": FakeLLM(*(responses or (draft_json(),))),
        "candidates": FakeDirectory(record if record is not None else make_record()),
        "detector": lambda text: False,
    }
    settings.update(overrides)
    return DrafterDeps(**settings)
