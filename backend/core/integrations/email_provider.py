# Email integration used by the executor: the fictional LocalMailbox (inbox files + outbox) and a
# simple sender with a demo outbox (default) or real SMTP delivery, used by HR replies

import json
import os
import re
import smtplib
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

from core.paths import data_dir, runtime_dir

UTC = timezone.utc  # datetime.UTC needs Python 3.11+


@dataclass(frozen=True)
class OutboundEmail:
    idempotency_key: str
    thread_id: str
    to: str
    subject: str
    body: str
    in_reply_to: str


class EmailProvider(Protocol):
    def send(self, email: OutboundEmail) -> None: ...

    def latest_inbound_id(self, thread_id: str) -> str | None: ...


class LocalMailbox:
    """A fictional mailbox. Inbound mail comes from JSON files, and "sent" mail goes to a local outbox file."""

    def __init__(self, inbox_paths: list[Path], outbox_path: Path) -> None:
        self._inbox_paths = inbox_paths
        self._outbox_path = outbox_path

    def inbound(self) -> list[dict[str, Any]]:
        emails: list[dict[str, Any]] = []
        for path in self._inbox_paths:
            if path.exists():
                emails.extend(json.loads(path.read_text(encoding="utf-8")))
        return sorted(emails, key=lambda email: email["received_at"])

    def get(self, email_id: str) -> dict[str, Any] | None:
        return next((email for email in self.inbound() if email["email_id"] == email_id), None)

    def outbox(self) -> list[dict[str, Any]]:
        if not self._outbox_path.exists():
            return []
        lines = self._outbox_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def latest_inbound_id(self, thread_id: str) -> str | None:
        emails = [email for email in self.inbound() if email["thread_id"] == thread_id]
        return emails[-1]["email_id"] if emails else None

    def thread_history(self, email: dict[str, Any]) -> list[dict[str, Any]]:
        """Return earlier messages in the email's thread, both received and sent."""
        history = [
            {
                "thread_id": other["thread_id"],
                "from_address": other["from_address"],
                "direction": "inbound",
                "subject": other["subject"],
                "body": other["body"],
                "sent_at": other["received_at"],
            }
            for other in self.inbound()
            if other["thread_id"] == email["thread_id"] and other["received_at"] < email["received_at"]
        ]
        history += [
            {
                "thread_id": sent["thread_id"],
                "from_address": "recruiting@hirewall.example",
                "direction": "outbound",
                "subject": sent["subject"],
                "body": sent["body"],
                "sent_at": sent["sent_at"],
            }
            for sent in self.outbox()
            if sent["thread_id"] == email["thread_id"] and sent["sent_at"] < email["received_at"]
        ]
        return sorted(history, key=lambda message: message["sent_at"])

    def send(self, email: OutboundEmail) -> None:
        if any(char in email.to + email.subject for char in "\r\n"):
            raise ValueError("line break in email header")
        if any(sent["idempotency_key"] == email.idempotency_key for sent in self.outbox()):
            return
        self._outbox_path.parent.mkdir(parents=True, exist_ok=True)
        record = {**asdict(email), "sent_at": datetime.now(UTC).isoformat()}
        with self._outbox_path.open("a", encoding="utf-8") as outbox:
            outbox.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_mailbox() -> LocalMailbox:
    data = data_dir()
    return LocalMailbox(
        [data / "emails" / "inbox.json", data / "attacks" / "emails.json"], runtime_dir() / "outbox.jsonl"
    )


# --- Simple sender for HR replies -------------------------------------------------------------------------
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
