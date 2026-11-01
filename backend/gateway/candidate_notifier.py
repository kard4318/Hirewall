# Tells a candidate about an approved decision: a rejection email, or an invitation from the Scheduler bot
"""Called only by core/executor, after a person approved. This is where the screener and scheduler meet, because
services may not import each other. The text is fixed: no model writes it, and it gives no score or reason."""
import logging
from datetime import datetime, timezone
from typing import Any

from core.integrations.email_provider import EmailDeliveryError, EmailSender
from services.scheduler.models import Job, PassedCandidate
from services.scheduler.service import COMPANY_NAME, Conflict, SchedulingService
from services.screener.service import ScreeningService

logger = logging.getLogger(__name__)

REJECTION_SUBJECT = "Your application for {job_title} at {company}"
REJECTION_BODY = (
    "Hello{name},\n\n"
    "Thank you for applying for {job_title} at {company}. After reviewing your application, we will not be moving "
    "forward with it.\n\n"
    "This decision was made by a member of our recruiting team. We wish you all the best in your search.\n\n"
    "The recruiting team\n{company}\n"
)
SHORTLIST_REASON = "Shortlisted by a recruiter after reviewing the application."


def _names(full_name: str | None) -> tuple[str, str]:
    first, _, last = " ".join((full_name or "").split()).partition(" ")
    return first, last


def scheduler_id(candidate_id: str, job_id: str) -> str:
    """The scheduler keeps one status per id, and one CV can be shortlisted for two jobs."""
    return f"{candidate_id}--{job_id}"


class CandidateNotifier:
    def __init__(self, screening: ScreeningService, scheduling: SchedulingService, email: EmailSender) -> None:
        self._screening = screening
        self._scheduling = scheduling
        self._email = email

    def notify(self, action_type: str, payload: dict[str, Any], candidate_id: str) -> str:
        """Returns `sent`, `outbox` (kept locally, not delivered), `no_email`, `in_progress` or `failed`."""
        purpose = "rejection" if action_type == "record_rejection" else "invitation"
        contact = self._screening.decision_contact(payload["run_id"], candidate_id, purpose)
        if not contact["email"]:
            return "no_email"
        try:
            if action_type == "record_rejection":
                return self._reject(contact, payload["job_id"], candidate_id)
            return self._invite(contact, payload["job_id"], candidate_id)
        except EmailDeliveryError as error:
            # Its text never holds the address or the message, but the type is all a log needs.
            logger.error("notification failed candidate=%s error_type=%s", candidate_id, type(error).__name__)
            return "failed"

    def _delivered(self, sender: Any) -> str:
        return "sent" if getattr(sender, "mode", "outbox") == "smtp" else "outbox"

    def _reject(self, contact: dict[str, Any], job_id: str, candidate_id: str) -> str:
        # Anyone shortlisted earlier must not keep a working booking link. An existing booking stays for HR to cancel.
        self._scheduling.withdraw_invitation(scheduler_id(candidate_id, job_id))
        first, _ = _names(contact["full_name"])
        company = contact["company"] or COMPANY_NAME
        self._email.send(
            contact["email"],
            REJECTION_SUBJECT.format(job_title=contact["job_title"], company=company),
            REJECTION_BODY.format(name=f" {first}" if first else "", job_title=contact["job_title"], company=company),
        )
        return self._delivered(self._email)

    def _invite(self, contact: dict[str, Any], job_id: str, candidate_id: str) -> str:
        first, last = _names(contact["full_name"])
        record = PassedCandidate(
            candidate_id=scheduler_id(candidate_id, job_id),
            first_name=first or "there",
            last_name=last,
            email=contact["email"],
            job_id=job_id,
            job_title=contact["job_title"],
            score=contact["score"],
            matched_skills=contact["matched_skills"],
            justification=SHORTLIST_REASON,
            screened_at=datetime.now(timezone.utc),
        )
        job = Job(job_id=job_id, title=contact["job_title"], location=contact["location"] or "")
        try:
            delivered = self._scheduling.invite_shortlisted(job, record)
        except Conflict:
            return "in_progress"
        return self._delivered(self._scheduling.deps.email) if delivered else "failed"
