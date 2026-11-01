# Tests for core/integrations/email_provider: outbox default, SMTP delivery (fake SMTP class), header safety
import smtplib

import pytest

from core.integrations import email_provider
from core.integrations.email_provider import (
    EmailDeliveryError,
    OutboxEmailSender,
    SmtpEmailSender,
    email_sender_from_env,
)


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    fail = False

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def starttls(self, context: object) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user))

    def send_message(self, message) -> None:
        if FakeSMTP.fail:
            raise smtplib.SMTPRecipientsRefused({})
        self.calls.append(("send", message["To"], message["Subject"], message.get_content()))


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch):
    FakeSMTP.instances, FakeSMTP.fail = [], False
    monkeypatch.setattr(email_provider.smtplib, "SMTP", FakeSMTP)


def test_outbox_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMAIL_MODE", raising=False)
    sender = email_sender_from_env()
    assert isinstance(sender, OutboxEmailSender) and sender.mode == "outbox"
    sender.send("lina@example.test", "Hello", "Body")
    assert sender.outbox[0]["to"] == "lina@example.test" and FakeSMTP.instances == []


def test_smtp_sends_with_starttls_and_login() -> None:
    SmtpEmailSender("smtp.example.test", 587, "hr@example.test", "app-pass", "hr@example.test").send(
        "lina@example.test", "Re: your question", "Line one\nLine two")
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.test", 587)
    assert smtp.calls[0] == "starttls" and smtp.calls[1] == ("login", "hr@example.test")
    assert smtp.calls[2][:3] == ("send", "lina@example.test", "Re: your question") and "Line two" in smtp.calls[2][3]


def test_smtp_failure_is_a_clear_error_without_the_body() -> None:
    FakeSMTP.fail = True
    with pytest.raises(EmailDeliveryError) as info:
        SmtpEmailSender("smtp.example.test", 587, "", "", "hr@example.test").send("a@example.test", "S", "secret body")
    assert "secret body" not in str(info.value)


@pytest.mark.parametrize("to,subject", [("a@example.test\nBcc: x@evil.test", "S"), ("not-an-email", "S"),
                                        ("a@example.test", "S\r\nBcc: x@evil.test")])
def test_header_injection_is_refused(to: str, subject: str) -> None:
    with pytest.raises(EmailDeliveryError):
        OutboxEmailSender().send(to, subject, "body")


def test_smtp_mode_needs_host_and_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_MODE", "smtp")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        email_sender_from_env()
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_FROM", "people@example.test")
    assert isinstance(email_sender_from_env(), SmtpEmailSender)
