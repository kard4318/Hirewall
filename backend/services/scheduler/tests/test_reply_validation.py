# Tests for the reply validator, placeholders and fallback templates
import pytest

from services.scheduler.conversation import fallbacks
from services.scheduler.conversation.formatting import SLOT, SLOTS, reply_problems
from services.scheduler.conversation.nodes.choice import resolve_slot
from services.scheduler.tests.conversation_harness import TUNIS


@pytest.mark.parametrize("text", [
    "See you Monday at 3:17! {{SLOTS}}", "How about 10am? {{SLOTS}}", "On 2026-11-03: {{SLOTS}}",
    "Free on 3/11 {{SLOTS}}", "Early November works {{SLOTS}}", "Tomorrow? {{SLOTS}}",
    "Book here https://evil.test {{SLOTS}}", "Write to x@evil.test {{SLOTS}}",
])
def test_unsafe_replies_rejected(text: str) -> None:
    assert reply_problems(text, SLOTS) is not None


def test_placeholder_rules() -> None:
    assert reply_problems("Here you go: {{SLOTS}}", SLOTS) is None
    assert reply_problems("Here you go!", SLOTS) is not None
    assert reply_problems("{{SLOTS}} {{SLOTS}}", SLOTS) is not None
    assert reply_problems("Picked {{SLOT}}", SLOTS) is not None
    assert reply_problems("No problem, tell me more.", None) is None
    assert reply_problems("Sure {{SLOT}}", None) is not None


def test_every_template_passes_its_own_validator() -> None:
    about_bookings = {"booked", "already_booked", "booking_rejected", "error"}  # fixed texts that may say "booked"
    for name, text in {**fallbacks.FALLBACKS, **fallbacks.FIXED}.items():
        required = SLOTS if SLOTS in text else SLOT if SLOT in text else None
        assert reply_problems(text, required, booked=name in about_bookings) is None, name
    for text in (fallbacks.LINK_INVALID, fallbacks.MESSAGE_BLOCKED):
        assert reply_problems(text, None) is None


OFFERED = [
    {"id": "s_aaaa1111", "start": "2026-11-02T10:00:00+01:00", "end": "2026-11-02T10:45:00+01:00"},
    {"id": "s_bbbb2222", "start": "2026-11-03T11:00:00+01:00", "end": "2026-11-03T11:45:00+01:00"},
    {"id": "s_cccc3333", "start": "2026-11-05T09:00:00+01:00", "end": "2026-11-05T09:45:00+01:00"},
]


@pytest.mark.parametrize("ref,expected", [
    ("s_bbbb2222", "s_bbbb2222"), ("2", "s_bbbb2222"), ("second", "s_bbbb2222"), ("the second one", "s_bbbb2222"),
    ("the last one", "s_cccc3333"), ("Thursday", "s_cccc3333"), ("#1", "s_aaaa1111"),
    ("4", None), ("s_ffff0000", None), ("friday", None), ("10:00", None), (None, None),
])
def test_resolve_slot(ref, expected) -> None:
    found = resolve_slot(ref, OFFERED, TUNIS, exact_only=False)
    assert (found["id"] if found else None) == expected


def test_resolve_slot_exact_only() -> None:
    assert resolve_slot("2", OFFERED, TUNIS, exact_only=True) is None
    assert resolve_slot("s_aaaa1111", OFFERED, TUNIS, exact_only=True)["id"] == "s_aaaa1111"
