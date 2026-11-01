# Template-based weekly recap sentences and rule-based highlights (no LLM; every highlight carries its numbers)
from collections import Counter
from datetime import date

from services.analytics import metrics
from services.analytics.config import DEPARTMENTS
from services.analytics.models import AuditEvent, Employee, EngagementRow, TrainingRow

ATTRITION_RATIO = 2.0
TRAINING_GAP = 0.25          # completion this far (25 points) below the company figure
ENGAGEMENT_DROP = 0.4


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def recap_sentences(events: list[AuditEvent]) -> list[str]:
    counts = Counter(e.event for e in events)
    outcome = Counter((e.event, e.outcome) for e in events)
    blocked = Counter(e.reason_code for e in events if e.event == "message_blocked")
    lines = []
    if counts["resume_screened"] or counts["booking_created"]:
        lines.append(f"{_plural(counts['resume_screened'], 'resume')} screened, {counts['candidate_shortlisted']} shortlisted "
                     f"and {_plural(counts['booking_created'], 'interview')} booked.")
    if counts["approval_decided"]:
        lines.append(f"HR made {_plural(counts['approval_decided'], 'approval decision')}: "
                     f"{outcome[('approval_decided', 'approve')]} approved, {outcome[('approval_decided', 'edit')]} edited "
                     f"and {outcome[('approval_decided', 'reject')]} rejected.")
    if counts["kb_question"]:
        lines.append(f"The handbook assistant answered {outcome[('kb_question', 'answered')]} of "
                     f"{_plural(counts['kb_question'], 'employee question')}; "
                     f"{outcome[('kb_question', 'escalated')]} were passed to the People Team.")
    if counts["message_blocked"]:
        top, _ = blocked.most_common(1)[0]
        lines.append(f"{_plural(counts['message_blocked'], 'message')} blocked by the security filters, "
                     f"most often for {top.replace('_', ' ')}.")
    if counts["reminder_drafted"] or counts["invitation_created"]:
        lines.append(f"{_plural(counts['invitation_created'], 'invitation')} sent by HR and "
                     f"{_plural(counts['reminder_drafted'], 'reminder')} drafted for candidates who had not replied.")
    return lines[:5] or ["No agent activity was recorded this week."]


def highlights(employees: list[Employee], engagement: list[EngagementRow], training: list[TrainingRow],
               as_of: date, period_start: date, min_size: int) -> list[dict]:
    """Up to 3 group-level findings. Each says which rule fired and the numbers behind it."""
    found: list[tuple[float, dict]] = []

    quarter = metrics.latest_complete_quarter(as_of)
    q_start, q_end = metrics.quarter_bounds(quarter)
    company = metrics.company_quarterly_average(employees, quarter)
    for dept in DEPARTMENTS:
        group = metrics.filter_employees(employees, department=dept)
        n = metrics.average_headcount(group, q_start, q_end)
        rate = metrics.attrition_rate(group, q_start, q_end)
        if company and rate is not None and n >= min_size and rate > ATTRITION_RATIO * company:
            found.append((rate / company, {
                "rule": "attrition_spike",
                "rule_text": f"latest quarterly attrition > {ATTRITION_RATIO:g}x the company quarterly average "
                             f"(last 8 quarters) with at least {min_size} people",
                "text": f"{dept} attrition was {rate:.1%} in {quarter}, {rate / company:.1f}x the company quarterly "
                        f"average of {company:.1%}.",
                "numbers": {"department": dept, "quarter": quarter, "rate": round(rate, 4),
                            "company_quarterly_average": round(company, 4), "ratio": round(rate / company, 2),
                            "exits": len(metrics.exits(group, q_start, q_end)), "n": n},
            }))

    dept_of = {e.employee_id: e.department for e in employees if metrics.is_active(e, as_of)}
    current = [r for r in training if r.employee_id in dept_of]
    overall, _, _ = metrics.training_completion(current)
    for dept in DEPARTMENTS:
        completion, _, n = metrics.training_completion(r for r in current if dept_of[r.employee_id] == dept)
        if overall is not None and completion is not None and n >= min_size and completion < overall - TRAINING_GAP:
            gap = overall - completion
            found.append((gap * 10, {
                "rule": "training_gap",
                "rule_text": f"training completion more than {TRAINING_GAP:.0%} points below the company figure "
                             f"with at least {min_size} people",
                "text": f"{dept} completed {completion:.0%} of assigned training, against {overall:.0%} company-wide.",
                "numbers": {"department": dept, "completion": round(completion, 4),
                            "company_completion": round(overall, 4), "gap": round(gap, 4), "n": n},
            }))

    window = [q for q in metrics.quarters_between(period_start, as_of) if metrics.quarter_bounds(q)[1] <= as_of]
    for dept in DEPARTMENTS:
        series = []
        for q in metrics.previous_quarters(window[-1], len(window) + 1) if window else []:
            score, respondents = metrics.engagement_score(r for r in engagement if r.department == dept and r.quarter == q)
            series.append((q, score, respondents))
        drops = [(a, b) for a, b in zip(series, series[1:])
                 if a[1] is not None and b[1] is not None and min(a[2], b[2]) >= min_size and a[1] - b[1] >= ENGAGEMENT_DROP]
        if drops:
            a, b = max(drops, key=lambda pair: pair[0][1] - pair[1][1])
            found.append(((a[1] - b[1]) * 5, {
                "rule": "engagement_drop",
                "rule_text": f"engagement fell by {ENGAGEMENT_DROP} or more from one quarter to the next "
                             f"with at least {min_size} respondents",
                "text": f"{dept} engagement fell from {a[1]:.1f} in {a[0]} to {b[1]:.1f} in {b[0]}.",
                "numbers": {"department": dept, "from_quarter": a[0], "to_quarter": b[0], "before": round(a[1], 2),
                            "after": round(b[1], 2), "drop": round(a[1] - b[1], 2), "n": min(a[2], b[2])},
            }))
    return [item for _, item in sorted(found, key=lambda pair: -pair[0])[:3]]
