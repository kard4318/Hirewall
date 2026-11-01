# LangGraph wiring for the candidate scheduling conversation (one graph run per candidate message)
import os
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from services.scheduler.calendar_source.provider import ReadOnlyCalendar
from services.scheduler.conversation.deps import Deps
from services.scheduler.conversation.nodes import answer, book, choice, find_slots, gate, reply, understand
from services.scheduler.conversation.state import SchedState
from services.scheduler.conversation.tokens import token_id


TRACING_VARS = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING")


def disable_tracing() -> None:
    """Candidate messages must never be shipped to a tracing service by a stray env var."""
    for name in TRACING_VARS:
        os.environ[name] = "false"


def build_graph(deps: Deps) -> Any:
    disable_tracing()
    if not isinstance(deps.calendar, ReadOnlyCalendar):
        raise TypeError("The scheduling graph only accepts a ReadOnlyCalendar; writes go through the BookingExecutor.")
    graph = StateGraph(SchedState)
    graph.add_node("gate", gate.make_node(deps))
    graph.add_node("understand", understand.make_node(deps))
    graph.add_node("find_slots", find_slots.make_node(deps))
    graph.add_node("choice", choice.make_node(deps))
    graph.add_node("book", book.make_node(deps))
    graph.add_node("answer", answer.make_node(deps))
    graph.add_node("reply", reply.make_node(deps))

    graph.add_edge(START, "gate")
    graph.add_conditional_edges("gate", lambda s: "reply" if s.get("blocked") else "understand", ["reply", "understand"])
    graph.add_conditional_edges("understand", understand.route, ["find_slots", "choice", "answer"])
    graph.add_conditional_edges("choice", choice.route, ["book", "reply"])
    for name in ("find_slots", "answer", "book"):
        graph.add_edge(name, "reply")
    graph.add_edge("reply", END)
    return graph.compile(checkpointer=MemorySaver())


def thread_config(token: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": token_id(token)}}


def run_turn(graph: Any, token: str, message: str | None = None, ui_action: dict[str, Any] | None = None) -> dict[str, Any]:
    """One candidate turn. ui_action is always sent (None when absent) so it never leaks into the next turn."""
    return graph.invoke({"token": token, "user_message": message or "", "ui_action": ui_action}, thread_config(token))


def resume_booking(graph: Any, token: str, approved: bool) -> dict[str, Any]:
    """Resume a STRICT_BOOKING_MODE approval interrupt with HR's decision."""
    return graph.invoke(Command(resume={"approved": approved}), thread_config(token))


def pending_approval(result: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = result.get("__interrupt__") or []
    return interrupts[0].value if interrupts else None
