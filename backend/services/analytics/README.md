# People Analytics service

Group-level workforce analytics for the HR dashboard (Overview, People, Retention & engagement), computed in pure
Python from the **synthetic** Northwind Labs data in `data/people/` and the shared audit events
(`docs/audit-events.md`). No LLM; recap text comes from templates.

## Privacy rules (enforced in code and tests)

- Employees are pseudonymous (`E-0001`); no **analytics** endpoint returns individual rows, ids, names or free text.
- The separate HR **directory** (`directory.py`, `/api/hr/directory`, HR token only) is the one place with
  identified records: fictional names and emails from `data/people/directory.csv`, which analytics never reads.
  It shows job and employment details, manager and training, but never age band or gender per person.
- Demographics are limited to `age_band` and `gender`, aggregate only. No race, ethnicity, religion or health data.
- Any group with fewer than `MIN_GROUP_SIZE` (default 5) people returns `{"suppressed": true}` instead of numbers.
  Complementary suppression: if exactly one group is hidden while the total is published, the next smallest group is
  hidden too, so the hidden value cannot be derived by subtraction (with two groups, both are hidden).
- No individual predictions or scores. Group-level insights only.
- This package must never be imported by `backend/services/screener` (tested). Screening never sees age or gender.

## Metric definitions

Let D be a date and [A, B] a period (both ends included).

- **Headcount at D**: employees with `hire_date <= D` and (`end_date` blank or `end_date > D`).
- **Hires in [A, B]**: employees with `A <= hire_date <= B`. **Exits in [A, B]**: employees with `A <= end_date <= B`.
- **Attrition rate for [A, B]**: exits in [A, B] / ((headcount at A + headcount at B) / 2).
  - Quarterly figure: [A, B] is a calendar quarter (truncated at `as_of` for the current quarter, flagged `partial`).
  - KPI `attrition_rate_12m`: the trailing 12 months, [D - 365 days, D], which is already an annual figure.
- **Company quarterly average**: mean of the company's quarterly attrition rates over the 8 complete quarters ending
  with the latest complete quarter.
- **Average tenure (years)**: mean of (D - hire_date) in days / 365.25 over employees active at D. Leavers' tenure
  uses end_date instead of D.
- **Voluntary share**: voluntary exits / all exits in the period.
- **Engagement**: respondent-weighted mean score; group size n = respondents.
- **Training completion**: completed assignments / assignments, for employees active at D; hours per person = total
  hours / people with at least one assignment.
- **Hours saved estimate**: minutes per audit event (`config.MINUTES_SAVED`: resume_screened 6, booking_created 4,
  kb_question answered 3, reminder_drafted 2, approval_decided 1) / 60.
- **Default period**: the 365 days ending at `ANALYTICS_AS_OF` (default 2026-11-01). The previous period is the
  same length, immediately before.

## Highlights (rules)

- `attrition_spike`: a department's attrition in the latest complete quarter is more than 2x the company quarterly
  average, with at least `MIN_GROUP_SIZE` people.
- `training_gap`: a department's training completion is more than 25 points below the company figure.
- `engagement_drop`: a department's engagement fell by 0.4 or more from one quarter to the next in the period.

Every highlight returns the rule, the rule text and the numbers that triggered it.

## Files

`config.py` (settings: `ANALYTICS_AS_OF`, `MIN_GROUP_SIZE`), `models.py`, `repository.py` (CSV and audit loading,
cached until files change), `metrics.py` (pure functions), `privacy.py`, `recap.py`, `reports.py` (endpoint
payloads). Routes: `backend/gateway/routers/analytics.py`, all under `/api/hr/analytics/*` and HR-authenticated.

## Run and test

```powershell
python scripts\generate_people_data.py            # seed 42, as of 2026-11-01
python -m pytest backend\services\analytics\tests
```
