# Dependencies injected into the scheduling graph (fakes in tests, real adapters in the app)
from dataclasses import dataclass, field

from services.scheduler.calendar_source.provider import ReadOnlyCalendar
from services.scheduler.config import ConversationSettings
from services.scheduler.conversation.llm import LLMClient
from services.scheduler.conversation.ports import AuditLog, BookingExecutor, BookingRepo, CandidateRepo, Clock, EmailSender


@dataclass
class Deps:
    llm: LLMClient
    calendar: ReadOnlyCalendar  # read-only on purpose; writes go through `executor`
    executor: BookingExecutor
    candidates: CandidateRepo
    bookings: BookingRepo
    email: EmailSender
    audit: AuditLog
    clock: Clock
    config: ConversationSettings = field(default_factory=ConversationSettings)
