# Test harness: builds the scheduling graph with fakes, MockCalendar and a fixed clock
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from services.scheduler.calendar_source.mock_calendar import MockCalendar
from services.scheduler.calendar_source.provider import ReadOnlyCalendar
from services.scheduler.config import ConversationSettings
from services.scheduler.conversation.adapters.calendar_executor import CalendarBookingExecutor
from services.scheduler.conversation.adapters.memory import (
    FixedClock,
    MemoryAuditLog,
    MemoryBookingRepo,
    MemoryCandidateRepo,
    MemoryEmailSender,
)
from services.scheduler.conversation.deps import Deps
from services.scheduler.conversation.graph import build_graph, run_turn
from services.scheduler.conversation.llm import FakeLLM
from services.scheduler.conversation.tokens import create_token

TUNIS = ZoneInfo("Africa/Tunis")
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=TUNIS)
SECRET = "test-secret-for-scheduler-conversation"
HR_EMAIL = "hr@example.test"
CANDIDATE = {"first_name": "Sara", "last_name": "Test", "email": "sara@example.test",
             "job_id": "job-da", "job_title": "Data Analyst", "status": "approved_for_interview"}


class ScriptedLLM:
    """Understand answers come from a queue; replies/answers are valid unless overridden."""

    def __init__(self, understand: list[Any], reply: Callable[[str], str] | None = None) -> None:
        self.understand = list(understand)
        self.reply = reply

    def __call__(self, system: str, user: str) -> str:
        if system.startswith("TASK: understand"):
            item = self.understand.pop(0) if self.understand else "not json"
            return item if isinstance(item, str) else json.dumps(item)
        if system.startswith("TASK: reply"):
            if self.reply:
                return self.reply(system)
            placeholder = re.search(r"^Required placeholder: (\S+)", system, re.M).group(1)
            text = "Thanks!" if placeholder == "none" else f"Thanks! {placeholder} Does that work?"
            return json.dumps({"message": text})
        return json.dumps({"answer": "The interview lasts about 45 minutes. HR can help with anything else."})


class RecordingExecutor(CalendarBookingExecutor):
    def __init__(self, provider: MockCalendar) -> None:
        super().__init__(provider)
        self.attendees: list[list[str]] = []

    def book(self, booking_id: str, slot: Any, summary: str, attendees: list[str]) -> tuple[str, str | None]:
        self.attendees.append(list(attendees))
        return super().book(booking_id, slot, summary, attendees)


@dataclass
class Harness:
    graph: Any
    deps: Deps
    mock: MockCalendar
    executor: RecordingExecutor
    llm: FakeLLM
    script: ScriptedLLM
    token: str

    def say(self, text: str) -> dict[str, Any]:
        return run_turn(self.graph, self.token, message=text)

    def click(self, action: dict[str, Any]) -> dict[str, Any]:
        return run_turn(self.graph, self.token, ui_action=action)

    @property
    def outbox(self) -> list[dict[str, str]]:
        return self.deps.email.outbox  # type: ignore[attr-defined]

    @property
    def audit(self) -> list[str]:
        return self.deps.audit.events()  # type: ignore[attr-defined]

    def calendar_events(self) -> int:
        return len(self.mock._events)


def make_harness(
    monkeypatch: Any,
    understand: list[Any] | None = None,
    reply: Callable[[str], str] | None = None,
    status: str = "approved_for_interview",
    strict: bool = False,
    **settings: Any,
) -> Harness:
    monkeypatch.setenv("SCHEDULER_TOKEN_SECRET", SECRET)
    mock = MockCalendar()
    executor = RecordingExecutor(mock)
    script = ScriptedLLM(understand or [], reply)
    llm = FakeLLM(script)
    deps = Deps(
        llm=llm,
        calendar=ReadOnlyCalendar(mock),
        executor=executor,
        candidates=MemoryCandidateRepo({"cand-sara": {**CANDIDATE, "status": status}}),
        bookings=MemoryBookingRepo(),
        email=MemoryEmailSender(),
        audit=MemoryAuditLog(),
        clock=FixedClock(NOW),
        config=ConversationSettings(tz=TUNIS, hr_email=HR_EMAIL, strict_booking=strict, **settings),
    )
    token = create_token("cand-sara", "job-da", 72, NOW)
    return Harness(build_graph(deps), deps, mock, executor, llm, script, token)
