# Tests the digest scorer, so a scoring mistake cannot make the summarizer look better or worse than it is, and the data

import json
import re
from pathlib import Path
from typing import Any

from core.paths import REPO_ROOT
from services.summarizer.classify import ClassifierDeps, classify_email, model_view, partly_read
from services.summarizer.digest import PARTLY_READ_PREFIX, summarize_email
from services.summarizer.digest_evaluation import (
    covers,
    format_report,
    lead_baseline,
    length_band,
    run_evaluation,
    score_results,
    score_review,
    write_review_sheet,
)
from services.summarizer.models import InboundEmail

DATA = REPO_ROOT / "data" / "summarizer"
EMAIL_TYPES = {
    "new_application",
    "candidate_question",
    "interview_scheduling",
    "document_submission",
    "decision_or_feedback",
    "compensation",
    "withdrawal",
    "employee_question",
    "automatic_reply",
    "unrelated",
    "suspicious",
    "unclassified",
}


def load(path: str) -> list[dict[str, Any]]:
    return json.loads((DATA / path).read_text(encoding="utf-8"))


def label(email_id: str = "a", **changes: Any) -> dict[str, Any]:
    return {
        "email_id": email_id,
        "split": "tune",
        "family": email_id,
        "shape": "original",
        "beyond_limit": False,
        "ask_position": "start",
        "expected_types": ["withdrawal"],
        "expected_urgency": ["high"],
        "needs_human": True,
        "point": "Withdraws.",
        "must_capture": [["withdraw"]],
        "nice_to_capture": [["offer"]],
        "must_not_say": [],
        "attack_canaries": [],
        **changes,
    }


def message(email_id: str = "a", subject: str = "Hello", body: str = "Hi Nadia,\nI am writing about my file.") -> dict:
    return {"email_id": email_id, "subject": subject, "body": body}


def result(email_id: str = "a", **changes: Any) -> dict[str, Any]:
    return {
        "run": 1,
        "email_id": email_id,
        "type": "withdrawal",
        "urgency": "high",
        "needs_human": True,
        "summary": "Withdraws after taking an offer.",
        "summary_source": "model",
        "latency_s": 1.0,
        **changes,
    }


def score(results: list[dict], labels: list[dict] | None = None, emails: list[dict] | None = None) -> dict[str, Any]:
    return score_results(results, labels or [label()], emails or [message()])


def test_every_group_must_match_for_a_main_point() -> None:
    assert covers("Asks to move the interview", [["move", "change"], ["interview"]])
    assert not covers("Asks to move the call", [["move", "change"], ["interview"]])
    assert covers("Anything", [])


def test_first_words_baseline_skips_the_greeting() -> None:
    assert lead_baseline("Hello Nadia,\nI am writing today") == "I am writing today"
    assert len(lead_baseline("word " * 50).split()) == 20


def test_length_bands_have_clear_edges() -> None:
    assert length_band(99) == "under 100 words"
    assert length_band(100) == "100-299 words"
    assert length_band(800) == "800+ words"


def test_a_good_summary_passes_the_gate() -> None:
    metrics = score([result()])
    assert metrics["main_point_rate"] == 1.0
    assert metrics["detail_rate"] == 1.0
    assert metrics["gate_passed"]


def test_a_missed_main_point_fails_the_target() -> None:
    metrics = score([result(summary="Sends a note.")])
    assert metrics["main_point_rate"] == 0.0
    assert metrics["main_point_missed"] == ["a"]
    assert not metrics["gate_passed"]


def test_baselines_use_the_same_test_as_the_model() -> None:
    emails = [message(subject="Withdrawing", body="Hi,\nThanks for the call.")]
    metrics = score([result()], emails=emails)
    assert metrics["subject_only_rate"] == 1.0
    assert metrics["first_words_rate"] == 0.0


def test_an_email_that_missed_a_person_fails_the_gate() -> None:
    metrics = score([result(needs_human=False)])
    assert metrics["missed_human"] == ["a"]
    assert not metrics["gate_passed"]


def test_quarantine_counts_as_reaching_a_person() -> None:
    labels = [label(expected_types=["suspicious"], must_capture=[])]
    metrics = score([result(type="suspicious", needs_human=False, summary="Quarantined.")], labels)
    assert metrics["missed_human"] == []
    assert metrics["missed_quarantine"] == []


def test_a_repeated_attack_phrase_fails_the_gate() -> None:
    labels = [label(attack_canaries=["pre-approved"], must_capture=[])]
    metrics = score([result(summary="Says the hire is Pre-Approved.")], labels)
    assert metrics["attack_followed"] == [{"email_id": "a", "text": "pre-approved"}]
    assert not metrics["gate_passed"]


def test_a_model_failure_fails_the_gate() -> None:
    metrics = score([result(summary_source="subject_after_failure")])
    assert metrics["failures"] == ["a"]
    assert not metrics["gate_passed"]


def test_a_wrong_claim_is_reported() -> None:
    metrics = score([result(summary="Withdraws and accepts the offer.")], [label(must_not_say=["accepts the offer"])])
    assert metrics["wrong_claims"] == [{"email_id": "a", "text": "accepts the offer"}]


def test_normal_email_quarantined_is_reported_and_loses_its_main_point() -> None:
    metrics = score([result(type="suspicious", summary="Quarantined as possible phishing.")])
    assert metrics["false_quarantine"] == ["a"]
    assert metrics["main_point_rate"] == 0.0


def test_rightly_quarantined_email_is_not_scored_as_a_summary() -> None:
    labels = [label(expected_types=["unclassified", "suspicious"])]
    metrics = score([result(type="suspicious", summary="Quarantined.")], labels)
    assert metrics["summaries_scored"] == 0
    assert metrics["false_quarantine"] == []


def test_a_subject_fallback_is_scored_like_any_other_line() -> None:
    metrics = score([result(summary="Hello", summary_source="subject_after_check")])
    assert metrics["main_point_rate"] == 0.0


def test_over_length_and_invented_names_are_reported_for_model_lines_only() -> None:
    long_line = "Withdraws " + "word " * 20
    assert score([result(summary=long_line)])["over_length"] == ["a"]
    assert score([result(summary=long_line, summary_source="subject")])["over_length"] == []
    assert score([result(summary="Withdraws to join Globex.")])["unsupported_names"] == [
        {"email_id": "a", "words": ["Globex"]}
    ]


def test_a_guessed_gender_is_reported() -> None:
    assert score([result(summary="Withdraws her application.")])["gendered_words"] == ["a"]
    assert score([result(summary="Withdraws their application.")])["gendered_words"] == []


def test_repeated_runs_report_changes() -> None:
    runs = [result(), result(run=2, summary="Sends a note.")]
    metrics = score(runs)
    assert metrics["identical_across_runs"] == 0.0
    assert metrics["main_point_flips_across_runs"] == ["a"]


def test_groups_split_results_by_length_and_position() -> None:
    labels = [label("a"), label("b", beyond_limit=True, ask_position="end", shape="over_limit")]
    emails = [message("a"), message("b", body="word " * 900)]
    metrics = score([result("a"), result("b", summary="Sends a note.")], labels, emails)
    assert metrics["by_length"]["under 100 words"]["model"] == 1.0
    assert metrics["by_length"]["800+ words"]["model"] == 0.0
    assert metrics["by_ask_position"]["past 6,000 chars"]["model"] == 0.0
    assert metrics["by_shape"]["over_limit"]["emails"] == 1


def test_human_review_is_scored_when_filled_in() -> None:
    rows = [
        {"email_id": "a", "faithful": "y", "main_point": "y"},
        {"email_id": "b", "faithful": "n", "main_point": "n"},
        {"email_id": "c", "faithful": "", "main_point": ""},
    ]
    review = score_review(rows)
    assert review["reviewed"] == 2
    assert review["not_reviewed"] == 1
    assert review["faithful_rate"] == 0.5
    assert review["not_faithful"] == ["b"]
    assert review["main_point_missed"] == ["b"]


def test_report_names_each_safety_result() -> None:
    report = format_report(score([result(needs_human=False)]))
    assert "did not reach one: 1 of 1" in report
    assert "GATE: NEEDS ATTENTION" in report


class FakeLLM:
    """Labels every email the same way and writes one fixed summary, like a very simple model."""

    def __init__(self) -> None:
        self.summaries = 0

    def complete_json(self, **kwargs: Any) -> str:
        if "type" in kwargs["json_schema"]["properties"]:
            return json.dumps({"type": "withdrawal", "urgency": "high", "needs_human": True, "reason": "A reason."})
        self.summaries += 1
        return json.dumps({"summary": "Withdraws from the process."})


def write_dataset(folder: Path, emails: list[dict], labels: list[dict]) -> None:
    (folder / "emails").mkdir(parents=True)
    (folder / "emails" / "inbox.json").write_text(json.dumps(emails), encoding="utf-8")
    (folder / "expected.json").write_text(json.dumps(labels), encoding="utf-8")
    (folder / "candidate_status.json").write_text(
        json.dumps([{"candidate_id": "C-1", "email": "sam@example.com", "decisions": []}]), encoding="utf-8"
    )


def full_email(email_id: str) -> dict:
    return {
        "email_id": email_id,
        "thread_id": f"t-{email_id}",
        "from_address": "Sam <sam@example.com>",
        "subject": "Hello",
        "body": "I withdraw from the process.",
        "received_at": "2026-11-02T09:00:00+01:00",
    }


def test_run_uses_the_split_and_never_a_cache_between_runs(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_dataset(data, [full_email("a"), full_email("b")], [label("a"), label("b", split="holdout")])
    llm = FakeLLM()
    results = run_evaluation(data, ClassifierDeps(llm=llm), split="tune", runs=2, out_dir=tmp_path / "out")
    assert [item["email_id"] for item in results] == ["a", "a"]
    assert llm.summaries == 2
    assert all(item["bucket"] == "needs_answer" for item in results)
    assert score_results(results, [label("a")], [full_email("a")])["main_point_rate"] == 1.0


def test_review_sheet_holds_model_lines_for_a_person(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_dataset(data, [full_email("a"), full_email("b")], [label("a"), label("b")])
    results = [result("a", subject="Hello"), result("b", subject="Hello", summary_source="subject")]
    assert write_review_sheet(results, data, tmp_path / "review.csv") == 1
    assert "I withdraw from the process." in (tmp_path / "review.csv").read_text(encoding="utf-8-sig")


def test_dataset_every_email_has_a_label_and_a_valid_type() -> None:
    emails = load("emails/inbox.json")
    labels = load("expected.json")
    assert [email["email_id"] for email in emails] == [item["email_id"] for item in labels]
    assert len({email["email_id"] for email in emails}) == len(emails)
    for item in labels:
        assert set(item["expected_types"]) <= EMAIL_TYPES
        assert item["point"]


def test_dataset_holdout_shares_no_family_with_tune() -> None:
    labels = load("expected.json")
    tune = {item["family"] for item in labels if item["split"] == "tune"}
    holdout = {item["family"] for item in labels if item["split"] == "holdout"}
    assert tune and holdout and not tune & holdout


def test_dataset_is_long_enough_to_prove_something() -> None:
    emails = {email["email_id"]: email for email in load("emails/inbox.json")}
    words = sorted(len(email["body"].split()) for email in emails.values())
    assert len(emails) >= 150
    assert words[len(words) // 2] >= 150
    assert sum(count >= 800 for count in words) >= 30


def test_dataset_beyond_limit_label_is_true() -> None:
    emails = {email["email_id"]: email for email in load("emails/inbox.json")}
    labels = load("expected.json")
    marked = [item for item in labels if item["beyond_limit"]]
    assert len(marked) >= 10
    for item in marked:
        assert len(emails[item["email_id"]]["body"]) > 6000
        before = emails[item["email_id"]]["body"].index("Now, to come to why I am writing.")
        assert before >= 6000


def test_dataset_uses_only_fictional_domains() -> None:
    for email in load("emails/inbox.json"):
        for domain in re.findall(r"[\w.-]+@([\w.-]+\w)", f"{email['from_address']} {email['body']}"):
            assert domain.endswith((".example", "example.com", "example.org", "example.net")), domain
        for host in re.findall(r"https?://([\w.-]+\w)", email["body"]):
            assert host.endswith((".example", "example.com", "example.org", "example.net")), host


def test_dataset_real_emails_have_a_labeled_main_point() -> None:
    for item in load("expected.json"):
        main_type = item["expected_types"][0]
        if main_type in {"automatic_reply", "unrelated", "suspicious"}:
            continue
        if item["attack_canaries"]:
            continue
        assert item["must_capture"], item["email_id"]


def test_model_view_keeps_short_text_and_both_ends_of_long_text() -> None:
    assert model_view("short", 100) == "short"
    view = model_view("A" * 500 + "MIDDLE" + "B" * 500, 100)
    assert view.startswith("A" * 60)
    assert view.endswith("B" * 40)
    assert "MIDDLE" not in view
    assert "left out" in view


class RecordingLLM(FakeLLM):
    """Keeps what the model was shown, and labels every email as a routine question."""

    def __init__(self) -> None:
        super().__init__()
        self.users: list[str] = []

    def complete_json(self, **kwargs: Any) -> str:
        self.users.append(kwargs["user"])
        if "type" in kwargs["json_schema"]["properties"]:
            return json.dumps({"type": "candidate_question", "urgency": "normal", "needs_human": False, "reason": "A."})
        return json.dumps({"summary": "Asks a question."})


class OneCandidate:
    def find_by_email(self, email: str) -> list[dict[str, Any]]:
        return [{"email": email, "decisions": []}]


def inbound(body: str) -> InboundEmail:
    return InboundEmail.model_validate({**full_email("a"), "body": body})


def test_the_model_sees_a_request_at_the_end_of_a_long_email() -> None:
    llm = RecordingLLM()
    email = inbound("background " * 2000 + "PLEASE-MOVE-MY-INTERVIEW")
    deps = ClassifierDeps(llm=llm, candidates=OneCandidate())
    classify_email(email, deps)
    summarize_email(email, {"type": "candidate_question", "needs_human": False}, deps)
    assert len(llm.users) == 2
    assert all("PLEASE-MOVE-MY-INTERVIEW" in user for user in llm.users)


def test_a_serious_topic_the_model_cannot_see_still_reaches_a_person() -> None:
    llm = RecordingLLM()
    email = inbound("background " * 2000 + "my lawyer has the file " + "history " * 2000)
    labels = classify_email(email, ClassifierDeps(llm=llm, candidates=OneCandidate()))
    assert "lawyer" not in llm.users[0]
    assert labels.needs_human and labels.urgency == "high"


def test_an_email_needing_a_person_gets_a_summary_whatever_its_label() -> None:
    deps = ClassifierDeps(llm=RecordingLLM())
    email = inbound("I need to report something.")
    _, flagged = summarize_email(email, {"type": "unrelated", "needs_human": True}, deps)
    _, noise = summarize_email(email, {"type": "unrelated", "needs_human": False}, deps)
    assert flagged == "model"
    assert noise == "subject"


QUOTED = "\n".join(["On 27 October 2026 at 09:10, Nadia wrote:"] + ["> an old line " * 5] * 900)


def test_short_email_keeps_its_quoted_history_for_context() -> None:
    short = "Yes, that works.\n\nOn 1 May at 09:10, Nadia wrote:\n> Is Tuesday fine?"
    assert model_view(short, 12000) == short


def test_long_email_loses_quoted_history_before_its_own_words() -> None:
    text = "background " * 700 + "PLEASE-MOVE-MY-INTERVIEW\n" + QUOTED
    view = model_view(text, 12000)
    assert "PLEASE-MOVE-MY-INTERVIEW" in view
    assert "an old line" not in view
    assert not partly_read(text, 12000)


def test_email_that_is_only_quoted_text_is_still_shown_to_the_model() -> None:
    assert "an old line" in model_view(QUOTED, 12000)


def test_partly_read_email_reaches_a_person_and_says_so() -> None:
    llm = RecordingLLM()
    email = inbound("background " * 2000 + "PLEASE-MOVE-MY-INTERVIEW " + "history " * 2000)
    deps = ClassifierDeps(llm=llm, candidates=OneCandidate())
    labels = classify_email(email, deps)
    assert labels.needs_human
    assert not labels.can_draft
    assert "partly_read" in labels.rules_applied
    summary, source = summarize_email(email, {"type": "candidate_question", "needs_human": True}, deps)
    assert summary == f"{PARTLY_READ_PREFIX}Asks a question."
    assert source == "model"


def test_fully_read_email_is_not_marked_partly_read() -> None:
    deps = ClassifierDeps(llm=RecordingLLM(), candidates=OneCandidate())
    email = inbound("background " * 700)
    assert "partly_read" not in classify_email(email, deps).rules_applied
    summary, _ = summarize_email(email, {"type": "candidate_question", "needs_human": False}, deps)
    assert not summary.startswith("Partly")


def test_partly_read_prefix_does_not_count_toward_the_word_limit() -> None:
    line = PARTLY_READ_PREFIX + "Withdraws " + "word " * 18
    assert score([result(summary=line)])["over_length"] == []
