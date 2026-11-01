# Knowledge desk used by the gateway: the assistant plus the anonymous question log and People Team escalations
import os
import threading
from typing import Any, Protocol

from core.llm.client import get_llm
from services.employee_qa.answerer import KnowledgeAssistant
from services.employee_qa.config import REPO_ROOT, KnowledgeSettings
from services.employee_qa.extractive import extractive_llm
from services.employee_qa.fallbacks.messages import PEOPLE_TEAM
from services.employee_qa.question_log import QuestionLog


REPLY_SUBJECT = "Re: your question to the People Team"
REPLY_BODY = (
    "Hello,\n\n"
    "{quote}"
    "{message}\n\n"
    "Best regards,\nThe People Team\n{people_team}\n"
)
MAX_REPLY_CHARS = 2000


class ReplyNotPossible(Exception):
    """The hand-off has no contact address (anonymous), so there is nobody to reply to."""



class EmailSender(Protocol):
    mode: str

    def send(self, to: str, subject: str, body: str) -> None: ...


class MemoryOutbox:
    """Keeps replies in memory: the default when no sender is passed in, as in tests."""

    mode = "outbox"

    def __init__(self) -> None:
        self.outbox: list[dict[str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.outbox.append({"to": to, "subject": subject, "body": body})


class KnowledgeDesk:
    def __init__(self, assistant: KnowledgeAssistant, log: QuestionLog, email: "EmailSender | None" = None) -> None:
        self.assistant = assistant
        self.log = log
        self.email = email or MemoryOutbox()
        self.lock = threading.Lock()  # one question at a time: a small local model handles one prompt well

    def ask(self, question: str, audience: str) -> dict[str, Any]:
        with self.lock:
            answer = self.assistant.ask(question, audience=audience)
            entry_id = self.log.add(question, answer, audience)
        return {
            "id": entry_id,
            "kind": answer.kind,
            "answer": answer.answer,
            "citations": [{"section_id": c.section_id, "title": c.title, "version": c.version} for c in answer.citations],
            "topic": answer.topic,
            "escalation_offered": answer.escalation_offered,
            "assistant_unavailable": answer.kind == "error",
        }

    def escalate(self, entry_id: str, contact: str | None) -> None:
        with self.lock:
            self.log.escalate(entry_id, contact)

    def resolve(self, entry_id: str) -> None:
        with self.lock:
            self.log.resolve(entry_id)

    def reply(self, entry_id: str, message: str) -> str:
        """HR's reply, typed and sent by a person: the human decision the golden rule asks for. Returns the delivery mode."""
        text = message.strip()
        if not text or len(text) > MAX_REPLY_CHARS:
            raise ValueError("reply must be 1-2000 characters")
        with self.lock:
            entry = self.log.get(entry_id)
            escalation = entry.get("escalation")
            if not escalation:
                raise KeyError(entry_id)
            if not escalation.get("contact"):
                raise ReplyNotPossible(entry_id)
            quote = f"You asked: \"{entry['question']}\"\n\n" if entry.get("question") else ""
            self.email.send(escalation["contact"], REPLY_SUBJECT,
                            REPLY_BODY.format(quote=quote, message=text, people_team=PEOPLE_TEAM))
            self.log.reply(entry_id, text, delivery=self.email.mode)
            return self.email.mode


def knowledge_provider() -> str:
    """KNOWLEDGE_LLM_PROVIDER wins; else LLM_PROVIDER if it is ollama/fake; else Ollama whenever LLM_MODEL is set.

    This lets the scheduler keep LLM_PROVIDER=openai (its OpenAI-compatible route to Ollama) while the knowledge
    assistant talks to Ollama natively with the same LLM_MODEL.
    """
    explicit = os.getenv("KNOWLEDGE_LLM_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    shared = os.getenv("LLM_PROVIDER", "").strip().lower()
    if shared in ("ollama", "fake"):
        return shared
    return "ollama" if os.getenv("LLM_MODEL", "").strip() else "fake"


def desk_from_env(email: "EmailSender | None" = None) -> KnowledgeDesk:
    """`email` comes from the gateway: services never build a real sender themselves (team rule 7)."""
    assistant = KnowledgeAssistant(get_llm(knowledge_provider(), fake=extractive_llm()), KnowledgeSettings())
    return KnowledgeDesk(assistant, QuestionLog(REPO_ROOT / "data" / "runtime" / "knowledge_log.json"), email)
