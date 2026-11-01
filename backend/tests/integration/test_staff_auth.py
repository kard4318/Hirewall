"""Named staff accounts: sign-in, roles, lockout, and tokens that cannot cross audiences."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.audit.audit_log import AuditLog
from gateway.auth.hr_auth import HRAuthError, _b64, _sign, create_role_token, verify_role_token
from gateway.auth.jwt import issue_token, read_token
from gateway.auth.login import LoginGuard, UserError, UserStore, hash_password, verify_password
from gateway.auth.roles import can
from gateway.main import create_app
from services.scheduler.service import SchedulingService
from services.scheduler.tests.conversation_harness import make_harness

PASSWORDS = {"admin.nour": "admin-password-1", "recruiter.sam": "recruiter-password", "emp.lea": "employee-password"}


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    harness = make_harness(monkeypatch)
    monkeypatch.setenv("HR_TOKEN_SECRET", "hr-secret-for-auth-tests")
    users = UserStore(tmp_path / "users.json")
    users.add("admin.nour", "Nour Admin", "hr_admin", PASSWORDS["admin.nour"])
    users.add("recruiter.sam", "Sam Recruiter", "recruiter", PASSWORDS["recruiter.sam"])
    users.add("emp.lea", "Lea Employee", "employee", PASSWORDS["emp.lea"])
    audit = AuditLog(tmp_path / "audit.jsonl")
    app = create_app(SchedulingService(harness.deps, None, harness.deps.bookings), users=users, audit_log=audit)
    app.state.login_guard = LoginGuard(max_failures=3, lockout=timedelta(minutes=15))
    return {"client": TestClient(app), "users": users, "audit": audit, "now": harness.deps.clock.now(), "app": app,
            "tmp": tmp_path}


def login(world, username, password=None, path="/api/hr/login"):
    return world["client"].post(path, json={"username": username, "password": password or PASSWORDS[username]})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_password_hash_round_trip():
    stored = hash_password("correct horse battery")
    assert stored.startswith("scrypt$") and "correct" not in stored
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong horse battery", stored)
    assert not verify_password("x", "not-a-hash")
    assert hash_password("same") != hash_password("same")


def test_users_file_holds_no_passwords(world):
    text = (world["tmp"] / "users.json").read_text(encoding="utf-8")
    assert all(password not in text for password in PASSWORDS.values())


@pytest.mark.parametrize(("username", "role", "password", "code"), [
    ("Bad Name", "recruiter", "long-enough-pw", "invalid_username"),
    ("ok.name", "superuser", "long-enough-pw", "unknown_role"),
    ("ok.name", "recruiter", "short", "weak_password"),
    ("emp.lea", "employee", "long-enough-pw", "user_exists"),
])
def test_bad_accounts_are_refused(world, username, role, password, code):
    with pytest.raises(UserError, match=code):
        world["users"].add(username, "X", role, password)


def test_hr_sign_in_names_the_person(world):
    body = login(world, "recruiter.sam").json()
    assert (body["username"], body["role"], body["display_name"]) == ("recruiter.sam", "recruiter", "Sam Recruiter")
    me = world["client"].get("/api/hr/me", headers=bearer(body["token"])).json()
    assert me == {"username": "recruiter.sam", "role": "recruiter", "display_name": "Sam Recruiter"}
    event = [e for e in world["audit"].entries() if e["event"] == "auth.login_succeeded"][0]
    assert event["fields"] == {"audience": "hr", "user": "recruiter.sam", "role": "recruiter"}


def test_wrong_password_and_unknown_user_look_the_same(world):
    wrong, unknown = login(world, "recruiter.sam", "nope"), login(world, "nobody.here", "nope")
    assert (wrong.status_code, wrong.json()) == (unknown.status_code, unknown.json()) == (401, {"detail": "invalid_credentials"})


def test_employee_cannot_use_the_hr_login_and_hr_cannot_use_the_employee_one(world):
    assert login(world, "emp.lea").status_code == 401
    assert login(world, "recruiter.sam", path="/api/employee/login").status_code == 401
    assert login(world, "emp.lea", path="/api/employee/login").status_code == 200


def test_employee_token_cannot_reach_hr_or_approve(world):
    employee = login(world, "emp.lea", path="/api/employee/login").json()["token"]
    for method, path in (("get", "/api/hr/me"), ("get", "/api/hr/approvals"), ("post", "/api/hr/approvals/x/decision")):
        assert getattr(world["client"], method)(path, headers=bearer(employee)).status_code == 401


def test_token_for_one_audience_fails_for_the_other(world):
    hr = issue_token("recruiter.sam", "recruiter", world["now"])
    employee = issue_token("emp.lea", "employee", world["now"])
    with pytest.raises(HRAuthError):
        read_token(hr, world["now"], "employee")
    with pytest.raises(HRAuthError):
        read_token(employee, world["now"], "hr")
    with pytest.raises(ValueError):
        create_role_token("hr", world["now"], username="emp.lea", user_role="employee")


def test_token_without_a_role_is_refused(world):
    body = _b64(json.dumps({"aud": "hr", "sub": "hr", "exp": 9999999999}).encode())
    with pytest.raises(HRAuthError, match="wrong role"):
        verify_role_token(f"hr.{body}.{_sign(body, 'hr')}", world["now"], "hr")


def test_tampered_role_breaks_the_signature(world):
    token = issue_token("recruiter.sam", "recruiter", world["now"])
    body = _b64(json.dumps({"aud": "hr", "sub": "recruiter.sam", "role": "hr_admin", "exp": 9999999999}).encode())
    forged = f"hr.{body}.{token.rsplit('.', 1)[1]}"
    with pytest.raises(HRAuthError, match="bad signature"):
        read_token(forged, world["now"], "hr")


def test_expired_token_is_refused(world):
    token = issue_token("recruiter.sam", "recruiter", world["now"])
    with pytest.raises(HRAuthError, match="expired"):
        read_token(token, world["now"] + timedelta(hours=9), "hr")


def test_lockout_after_repeated_failures(world):
    assert [login(world, "recruiter.sam", "nope").status_code for _ in range(3)] == [401, 401, 401]
    locked = login(world, "recruiter.sam")
    assert (locked.status_code, locked.json()) == (429, {"detail": "account_locked"})
    events = [(e["event"], e["fields"]) for e in world["audit"].entries()]
    assert ("auth.account_locked", {"audience": "hr", "user": "recruiter.sam"}) in events
    assert all("nope" not in json.dumps(fields) for _, fields in events)


def test_lockout_ends_and_success_resets_the_count(world):
    guard = LoginGuard(max_failures=2, lockout=timedelta(minutes=15))
    now = world["now"]
    assert guard.failed("a", now) is False
    guard.succeeded("a")
    assert guard.failed("a", now) is False
    assert guard.failed("a", now) is True and guard.locked("a", now)
    assert not guard.locked("a", now + timedelta(minutes=16))


def test_unknown_usernames_are_never_recorded(world):
    login(world, "Pa$$word-typed-in-the-wrong-box", "x")
    assert "Pa$$word" not in (world["tmp"] / "audit.jsonl").read_text(encoding="utf-8")


def test_only_hr_admin_manages_users(world):
    recruiter = bearer(login(world, "recruiter.sam").json()["token"])
    admin = bearer(login(world, "admin.nour").json()["token"])
    assert world["client"].get("/api/hr/users", headers=recruiter).status_code == 403
    rows = world["client"].get("/api/hr/users", headers=admin).json()["users"]
    assert {r["username"] for r in rows} == set(PASSWORDS) and all("password_hash" not in r for r in rows)
    created = world["client"].post("/api/hr/users", headers=admin, json={
        "username": "recruiter.new", "display_name": "New", "role": "recruiter", "password": "new-password-1"})
    assert created.status_code == 201 and login(world, "recruiter.new", "new-password-1").status_code == 200
    assert world["client"].delete("/api/hr/users/admin.nour", headers=admin).status_code == 409
    assert world["client"].delete("/api/hr/users/recruiter.new", headers=admin).status_code == 200
    events = [e["fields"] for e in world["audit"].entries() if e["event"] == "auth.user_created"]
    assert events == [{"user": "recruiter.new", "role": "recruiter", "by": "admin.nour"}]


def test_permission_table_denies_by_default():
    assert can("recruiter", "approve") and can("hr_admin", "security_view")
    assert not can("recruiter", "security_view") and not can("employee", "approve")
    assert not can("hr_admin", "made_up_permission") and not can(None, "approve") and not can("", "approve")


def test_passcode_login_is_gone(world):
    assert world["client"].post("/api/hr/login", json={"passcode": "anything"}).status_code == 422
