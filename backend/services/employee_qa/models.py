# Data models used by the employee_qa service
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Audience = Literal["employee", "hr"]
Kind = Literal["answered", "not_found", "refused_personal", "sensitive", "blocked", "error"]


@dataclass(frozen=True)
class Section:
    section_id: str      # stable id, e.g. "leave-policy#1.1"
    doc_id: str
    doc_title: str
    number: str          # "1.1"
    heading: str         # "Entitlement"
    parent: str          # "Annual leave" for a ### section, "" for a ## section
    text: str
    audience: str        # "everyone" | "hr"
    version: str
    topic: str

    @property
    def title(self) -> str:
        path = f"{self.parent} > {self.heading}" if self.parent else self.heading
        return f"{self.doc_title} > {self.number} {path}"


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    audience: str
    version: str
    effective_date: str
    topic: str
    supersedes: tuple[str, ...]
    status: str
    sections: tuple[Section, ...]
    neutralized: int = 0  # instruction-like sentences removed at ingest


@dataclass(frozen=True)
class Citation:
    section_id: str
    title: str
    version: str


@dataclass
class Answer:
    kind: Kind
    answer: str
    citations: list[Citation] = field(default_factory=list)
    topic: str = ""
    mode: str = "none"              # full | retrieval | none (pre-check or abstention without an LLM call)
    escalation_offered: bool = False
    notice: str | None = None       # operator hint (e.g. "start Ollama"); never shown as policy text


class LLMAnswer(BaseModel):
    """The only shape accepted from the model."""

    model_config = ConfigDict(extra="ignore")
    answerable: bool
    answer: str = Field(default="", max_length=2000)
    citations: list[str] = Field(default_factory=list, max_length=8)
    topic: str = Field(default="", max_length=60)
