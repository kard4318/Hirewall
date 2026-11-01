# Answers employee questions only from accessible company documents, with validated citations
import html
import re
import time
from pathlib import Path

from core.llm.client import LLMError, LLMUnavailableError, TextLLM, estimate_tokens
from core.llm.structured_output import StructuredOutputError, structured
from services.employee_qa.access_control import accessible_sections, forbidden_documents
from services.employee_qa.audit import AuditLog, MemoryAuditLog
from services.employee_qa.config import KnowledgeSettings
from services.employee_qa.fallbacks import messages
from services.employee_qa.ingest import load_corpus
from services.employee_qa.models import Answer, Citation, Document, LLMAnswer, Section
from services.employee_qa.prechecks import normalise, precheck
from services.employee_qa.retriever import Selection, choose_strategy

SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "answer.md").read_text(encoding="utf-8")
CONTACT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|https?://\S+|www\.\S+", re.IGNORECASE)
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _attr(value: str) -> str:
    return html.escape(value, quote=True)


def build_prompt(sections: list[Section], question: str) -> str:
    blocks = "\n".join(
        f'<section id="{_attr(s.section_id)}" title="{_attr(s.title)}" version="{_attr(s.version)}">\n'
        f"{html.escape(s.text, quote=False)}\n</section>"
        for s in sections
    )
    return (f"<documents>\n{blocks}\n</documents>\n\n"
            f"<employee_question>\n{html.escape(question, quote=False)}\n</employee_question>")


class KnowledgeAssistant:
    def __init__(self, llm: TextLLM, settings: KnowledgeSettings | None = None, audit: AuditLog | None = None,
                 documents: list[Document] | None = None) -> None:
        self.llm = llm
        self.settings = settings or KnowledgeSettings()
        self.audit = audit or MemoryAuditLog()
        self.documents = documents if documents is not None else load_corpus(self.settings.docs_dir)[0]
        self.last_prompt: str | None = None  # for the eval's access checks; never logged

    def ask(self, question: str, audience: str = "employee", mode: str = "auto") -> Answer:
        started = time.perf_counter()
        self.last_prompt = None
        answer = self._answer(normalise(question or ""), audience, mode)
        self.audit.record("knowledge_answer", kind=answer.kind, topic=answer.topic, mode=answer.mode,
                          section_ids=[c.section_id for c in answer.citations], audience=audience,
                          reason=getattr(answer, "_reason", None),
                          latency_ms=round((time.perf_counter() - started) * 1000),
                          prompt_tokens=estimate_tokens(self.last_prompt) if self.last_prompt else 0)
        return answer

    # --- pipeline -----------------------------------------------------------------------------------------
    def _answer(self, question: str, audience: str, mode: str) -> Answer:
        if not question:
            return Answer("not_found", messages.EMPTY)
        if len(question) > self.settings.max_question_chars:
            return self._reason(Answer("blocked", messages.BLOCKED), "too_long")
        check = precheck(question)
        if check == "blocked":
            return self._reason(Answer("blocked", messages.BLOCKED), "injection")
        if check == "sensitive":
            return Answer("sensitive", messages.SENSITIVE, topic="sensitive", escalation_offered=True)
        if check == "refused_personal":
            return Answer("refused_personal", messages.REFUSED_PERSONAL, topic="personal records",
                          escalation_offered=True)

        sections = accessible_sections(self.documents, audience)  # access filter BEFORE anything else
        cfg = self.settings
        selection: Selection = choose_strategy(sections, mode, cfg.full_context_token_budget,
                                               cfg.retrieval_top_k, cfg.bm25_min_score).select(question)
        if not selection.sections:  # nothing relevant enough: abstain without calling the LLM
            return self._reason(Answer("not_found", messages.NOT_FOUND, mode=selection.mode,
                                       escalation_offered=True), "low_retrieval_score")

        self.last_prompt = build_prompt(selection.sections, question)
        try:
            result = structured(self.llm, SYSTEM_PROMPT, self.last_prompt, LLMAnswer)
        except LLMUnavailableError as exc:
            answer = Answer("error", messages.ERROR, mode=selection.mode, escalation_offered=True, notice=str(exc))
            return self._reason(answer, "llm_unavailable")
        except (LLMError, StructuredOutputError) as exc:
            answer = Answer("error", messages.ERROR, mode=selection.mode, escalation_offered=True,
                            notice=f"LLM failed: {type(exc).__name__}")
            return self._reason(answer, "llm_failed")
        return self._validate(result, selection, audience)

    def _validate(self, result: LLMAnswer, selection: Selection, audience: str) -> Answer:
        not_found = Answer("not_found", messages.NOT_FOUND, mode=selection.mode, escalation_offered=True)
        text = " ".join(result.answer.split())
        if not result.answerable or not text:
            return self._reason(not_found, "model_abstained")

        supplied = {s.section_id: s for s in selection.sections}
        cited = [supplied[c] for c in dict.fromkeys(result.citations) if c in supplied]  # invented ids dropped
        if not cited:
            return self._reason(not_found, "no_valid_citation")

        cited_text = " ".join(s.text for s in cited).lower()
        if any(contact.lower().rstrip(".,;)") not in cited_text for contact in CONTACT.findall(text)):
            return self._reason(not_found, "unsupported_contact")

        lowered = text.lower()
        for doc in forbidden_documents(self.documents, audience):
            if doc.doc_id in lowered or doc.title.lower() in lowered:
                return self._reason(not_found, "leak_blocked")

        sentences = SENTENCE.split(text)[: self.settings.max_answer_sentences]
        text = " ".join(sentences)
        if len(text) > self.settings.max_answer_chars:
            text = text[: self.settings.max_answer_chars].rsplit(" ", 1)[0] + "…"
        return Answer("answered", text, [Citation(s.section_id, s.title, s.version) for s in cited],
                      topic=cited[0].topic, mode=selection.mode)

    @staticmethod
    def _reason(answer: Answer, reason: str) -> Answer:
        answer._reason = reason  # type: ignore[attr-defined]  # audit reason code only
        return answer
