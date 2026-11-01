# Email integration used by the executor: a demo outbox (default) or real delivery over SMTP (stdlib only)
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Protocol

ADDRESS = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


class EmailDeliveryError(RuntimeError):
    """The message could not be delivered; the text says why (never includes the body)."""


class EmailSender(Protocol):
    mode: str

    def send(self, to: str, subject: str, body: str) -> None: ...


def _check(to: str, subject: str) -> None:
    # One plain address and a single-line subject: no header injection.
    if not ADDRESS.match(to) or "\n" in subject or "\r" in subject:
        raise EmailDeliveryError("invalid recipient or subject")


class OutboxEmailSender:
    """Keeps messages in memory and delivers nothing: the safe default for demos with fictional addresses."""

    mode = "outbox"

    def __init__(self) -> None:
        self.outbox: list[dict[str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        _check(to, subject)
        self.outbox.append({"to": to, "subject": subject, "body": body,
                            "at": datetime.now(timezone.utc).isoformat()})


class SmtpEmailSender:
    """Real delivery, e.g. Gmail: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, an app password as SMTP_PASSWORD."""

    mode = "smtp"

    def __init__(self, host: str, port: int, user: str, password: str, sender: str, starttls: bool = True,
                 timeout: float = 20.0) -> None:
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender, self.starttls, self.timeout = sender, starttls, timeout

    def send(self, to: str, subject: str, body: str) -> None:
        _check(to, subject)
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self.sender, to, subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                if self.starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if self.user:
                    smtp.login(self.user, self.password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailDeliveryError(f"SMTP delivery failed ({type(exc).__name__})") from None


def email_sender_from_env() -> EmailSender:
    mode = os.getenv("EMAIL_MODE", "outbox").strip().lower()
    if mode == "outbox":
        return OutboxEmailSender()
    if mode == "smtp":
        host, sender = os.getenv("SMTP_HOST", "").strip(), os.getenv("SMTP_FROM", "").strip()
        if not host or not sender:
            raise RuntimeError("EMAIL_MODE=smtp needs SMTP_HOST and SMTP_FROM (and usually SMTP_USER / SMTP_PASSWORD).")
        return SmtpEmailSender(host, int(os.getenv("SMTP_PORT") or 587), os.getenv("SMTP_USER", ""),
                               os.getenv("SMTP_PASSWORD", ""), sender,
                               starttls=os.getenv("SMTP_STARTTLS", "true").strip().lower() in ("1", "true", "yes"))
    raise RuntimeError(f"Unknown EMAIL_MODE {mode!r}; use outbox or smtp.")
