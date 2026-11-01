# Right to erasure: remove one candidate from every store, across services, and keep an ID-only audit trail
"""Lives in the gateway because it spans services, which may not import each other.

Audit entries are kept: they hold IDs, hashes and reason codes only, and the hash chain must stay verifiable.
"""
from typing import Any

from security.quarantine import QuarantineLog, SecuritySettings
from services.scheduler.service import Conflict


class ErasureBlocked(Exception):
    """A short reason code, for example interview_booked."""


def erase_everywhere(
    candidate_id: str, *, by: str, screening: Any, queue: Any, audit: Any, scheduling: Any = None,
    quarantine: QuarantineLog | None = None,
) -> dict[str, int]:
    names = screening.known_names(candidate_id)  # read before the identity is deleted
    counts: dict[str, int] = {}
    if scheduling is not None:
        try:
            counts["scheduler_records"] = scheduling.erase_screened(candidate_id)
        except Conflict:
            raise ErasureBlocked("interview_booked") from None
    counts.update(screening.erase_candidate(candidate_id))
    counts["approvals_withdrawn"] = len(queue.withdraw_for_candidate(candidate_id))
    log = quarantine if quarantine is not None else QuarantineLog(SecuritySettings().log_path)
    counts["quarantine_entries"] = log.erase_matching(names)
    audit.record("privacy.candidate_erased", candidate_id=candidate_id, by=by, **counts)
    return counts
