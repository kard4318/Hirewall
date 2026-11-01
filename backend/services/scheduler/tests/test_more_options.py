# Tests that "other times" offers new slots, never repeats shown ones, and words the reply accordingly
import pytest

from services.scheduler.conversation.formatting import SLOTS
from services.scheduler.conversation.nodes.reply import variant_of
from services.scheduler.tests.conversation_harness import make_harness

ASK = {"intent": "ask_slots"}
MORE = {"intent": "ask_slots", "more_options": True}


def test_other_times_are_new_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    h = make_harness(monkeypatch, [ASK, MORE, MORE])
    first = h.say("which times do you have?")["offered"]
    second = h.say("are there any other free spots?")
    third = h.say("and any others?")
    ids = [s["id"] for s in first] + [s["id"] for s in second["offered"]] + [s["id"] for s in third["offered"]]
    assert second["facts"]["more"] is True and len(second["offered"]) == 3
    assert len(ids) == len(set(ids))  # nothing is ever offered twice


def test_other_times_reply_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def reply(system: str) -> str:
        seen.append(system)
        return '{"message": "Of course! ' + SLOTS + ' Any of these?"}'

    h = make_harness(monkeypatch, [ASK, MORE], reply=reply)
    h.say("slots?")
    h.say("anything else?")
    assert "Kind: slots_offered_more" in seen[-1] and "asked for other options" in seen[-1]


def test_new_ask_without_more_starts_over(monkeypatch: pytest.MonkeyPatch) -> None:
    h = make_harness(monkeypatch, [ASK, MORE, ASK])
    first = h.say("slots?")["offered"]
    h.say("others?")
    again = h.say("what times do you have?")
    assert again["offered"] == first and again["shown_starts"] == [s["start"] for s in first]


def test_running_out_of_new_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    pref = {"dates_from": "2026-11-03", "dates_to": "2026-11-03"}
    asks = [{"intent": "ask_slots", "preference": pref}] + [{"intent": "ask_slots", "preference": pref, "more_options": True}] * 4
    h = make_harness(monkeypatch, asks)
    results = [h.say("Tuesday please")] + [h.say("other times on Tuesday?") for _ in range(4)]
    last = results[-1]
    assert last["facts"] == {"kind": "no_slots", "reason": "no_more"}
    assert "no_slots" in h.audit and h.calendar_events() == 0


def test_variant_selection() -> None:
    assert variant_of("slots_offered", {"more": True}) == "slots_offered_more"
    assert variant_of("slots_offered", {"preference": True}) == "slots_offered_preference"
    assert variant_of("no_slots", {"reason": "no_more"}) == "no_slots_no_more"
    assert variant_of("booked", {}) == "booked"
