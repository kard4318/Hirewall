# HTTP routes for the security page (hr_admin only): screening verdicts, refused uploads, model integrity,
# audit-chain status, the latest attack report and recent security events. IDs, codes and masked excerpts only.
import json
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Request

from core.paths import REPO_ROOT
from gateway.orchestration import screening_service
from gateway.routers.hr_scheduling import require_permission
from security.injection_model import model_integrity
from security.quarantine import SecuritySettings

router = APIRouter(prefix="/api/hr/security", dependencies=[Depends(require_permission("security_view"))])

ATTACK_REPORT = REPO_ROOT / "data" / "runtime" / "attack_report.json"
SECURITY_EVENTS = ("auth.login_failed", "auth.account_locked", "auth.login_refused", "auth.user_created",
                   "auth.user_deleted", "approval.refused", "privacy.candidate_erased", "privacy.retention_applied",
                   "screener.identity_revealed")
FIELDS = ("approval_id", "candidate_id", "user", "by", "reason", "status", "audience", "role", "reviewer")


def _quarantine() -> list[dict[str, Any]]:
    path = SecuritySettings().log_path
    if not path or not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def _attack_report() -> dict[str, Any] | None:
    if not ATTACK_REPORT.is_file():
        return None
    report = json.loads(ATTACK_REPORT.read_text(encoding="utf-8"))
    owasp: dict[str, dict[str, int]] = {}
    for row in report["results"]:
        for code in row["owasp"]:
            bucket = owasp.setdefault(code, {"total": 0, "stopped": 0})
            bucket["total"] += 1
            bucket["stopped"] += row["result"] == "pass"
    return {
        "generated_at": report["generated_at"], "mode": report["mode"], "total": report["total"],
        "stopped": report["stopped"], "pass_rate": report["pass_rate"], "owasp": owasp,
        "failed": [{k: row[k] for k in ("id", "title", "expected", "actual")} for row in report["results"]
                   if row["result"] != "pass"],
    }


@router.get("/summary")
def summary(request: Request) -> dict[str, Any]:
    quarantine = _quarantine()
    verdicts = Counter((e.get("action"), e.get("source") or "unknown") for e in quarantine)
    reasons = Counter(reason for e in quarantine for reason in e.get("reasons") or [])
    audit = request.app.state.audit
    broken = audit.first_broken()
    entries = audit.entries()
    events = [
        {"at": e["at"], "event": e["event"], **{k: e["fields"][k] for k in FIELDS if e["fields"].get(k) is not None}}
        for e in reversed(entries) if e["event"] in SECURITY_EVENTS
    ][:30]
    settings = SecuritySettings()
    return {
        "verdicts": [{"action": action, "source": source, "count": count}
                     for (action, source), count in sorted(verdicts.items(), key=lambda item: -item[1])],
        "reasons": dict(reasons.most_common()),
        "uploads_refused": screening_service(request.app).upload_refusals(),
        "model": {"mode": settings.mode, "integrity": model_integrity()},
        "audit": {"entries": len(entries), "intact": broken is None, "first_broken": broken},
        "attack_report": _attack_report(),
        "recent_quarantine": [
            {"at": e.get("at"), "action": e.get("action"), "source": e.get("source"), "reasons": e.get("reasons"),
             "excerpt": e.get("excerpt")}  # already masked when written
            for e in reversed(quarantine[-20:])
        ],
        "recent_events": events,
    }
