"""Team rules 6 and 7, checked on the code itself: services import only core/ and security/, and never the executor
or the integrations that send. Also the action policy and the local-only model rule."""
import ast
from pathlib import Path

import pytest

from core.approval_queue.approval_queue import ApprovalQueue, action_hash
from core.audit.audit_log import AuditLog
from core.candidate_status.store import CandidateStatusStore
from core.executor.executor import execute_record
from core.llm.client import is_local_url
from security.permissions import POLICY, execution_refusal, may_approve, policy_for

SERVICES = Path(__file__).resolve().parents[1] / "services"
FORBIDDEN = ("core.executor", "core.integrations")


def imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def service_files():
    return [p for p in SERVICES.rglob("*.py") if "tests" not in p.relative_to(SERVICES).parts]


def test_services_never_import_the_executor_or_integrations():
    offenders = [
        f"{path.relative_to(SERVICES)}: {name}"
        for path in service_files()
        for name in imports_of(path)
        if any(name == f or name.startswith(f + ".") for f in FORBIDDEN)
    ]
    assert offenders == []


def test_services_never_import_another_service():
    offenders = []
    for path in service_files():
        own = path.relative_to(SERVICES).parts[0]
        for name in imports_of(path):
            parts = name.split(".")
            if parts[0] == "services" and len(parts) > 1 and parts[1] != own:
                offenders.append(f"{path.relative_to(SERVICES)}: {name}")
    assert offenders == []


def test_the_scan_finds_a_forbidden_import(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("from core.executor.executor import execute_record\nimport core.integrations.email_provider\n")
    assert imports_of(bad) == ["core.executor.executor", "core.integrations.email_provider"]


def test_every_external_action_needs_a_human():
    assert POLICY and all(policy.human_approval for policy in POLICY.values())
    assert {"send_email", "record_shortlist", "record_rejection", "book_interview", "cancel_interview"} <= set(POLICY)


@pytest.mark.parametrize(("action", "executor", "approved_by", "reason"), [
    ("transfer_money", "core.executor.execute_record", "sam", "unknown_action"),
    (None, "core.executor.execute_record", "sam", "unknown_action"),
    ("send_email", "core.executor.execute_record", "sam", "wrong_executor"),
    ("record_shortlist", "core.executor.execute_record", "", "no_human_approval"),
    ("record_shortlist", "core.executor.execute_record", "sam", None),
])
def test_execution_policy(action, executor, approved_by, reason):
    assert execution_refusal(action, executor, approved_by) == reason


def test_who_may_approve():
    assert may_approve("record_shortlist", "recruiter") and may_approve("send_email", "hr_admin")
    assert not may_approve("record_shortlist", "employee") and not may_approve("transfer_money", "hr_admin")
    assert policy_for("") is None


def test_executor_refuses_and_audits_an_unknown_action(tmp_path):
    queue, audit = ApprovalQueue(tmp_path / "q.sqlite3"), AuditLog(tmp_path / "audit.jsonl")
    payload = {"job_id": "j", "run_id": "r", "candidate_ids": ["c"]}
    item = queue.submit({"action_type": "delete_everyone", "payload": payload, "in_reply_to": "x",
                         "payload_hash": action_hash("delete_everyone", payload), "idempotency_key": "k"}, "t")
    queue.approve(item.id, "recruiter.sam", item.payload_hash)
    result = execute_record(item.id, queue=queue, status_store=CandidateStatusStore(tmp_path / "s.sqlite3"), audit=audit)
    assert (result.status, result.reason) == ("refused", "unknown_action")
    event = audit.entries()[-1]
    assert event["event"] == "executor.outcome" and event["fields"]["reason"] == "unknown_action"
    assert queue.get(item.id).status == "approved"


@pytest.mark.parametrize(("url", "local"), [
    ("http://localhost:11434/v1", True), ("http://127.0.0.1:11434", True), ("https://api.openai.com/v1", False),
    ("http://localhost.evil.example/v1", False), ("", False), (None, False),
])
def test_only_local_model_servers(url, local):
    assert is_local_url(url) is local


def test_scheduler_refuses_cloud_models(monkeypatch):
    from services.scheduler.conversation.llm import LLMConfigError, get_llm

    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.setenv("LLM_MODEL", "m")
    with pytest.raises(LLMConfigError, match="Cloud models are not allowed"):
        get_llm("anthropic")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    with pytest.raises(LLMConfigError, match="this machine"):
        get_llm("openai")
    monkeypatch.delenv("LLM_BASE_URL")
    with pytest.raises(LLMConfigError, match="this machine"):
        get_llm("openai")
