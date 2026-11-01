# API Contract

Source of truth for every HTTP endpoint, request and response; written before any code.

TODO

## Screener to Scheduler handoff

The screener publishes who passed screening; the scheduler only reads it, through the `ScreenerResults` port
(`backend/services/scheduler/conversation/ports.py`). Until the real screener exists, the scheduler reads the mock
files `data/screener_mock/jobs.json` and `data/screener_mock/candidates.json` with exactly these shapes.

- `list_jobs() -> list[Job]`
- `list_passed(job_id) -> list[PassedCandidate]`, sorted by `score`, highest first

`Job`

| Field | Type | Notes |
|---|---|---|
| `job_id` | string | stable id, e.g. `job-be` |
| `title` | string | e.g. `Backend Developer` |
| `location` | string | optional, free text |

`PassedCandidate`

| Field | Type | Notes |
|---|---|---|
| `candidate_id` | string | stable id, unique across jobs |
| `first_name`, `last_name` | string | fictional in all demo data |
| `email` | string | `@example.test` only in demo data |
| `job_id`, `job_title` | string | the job this candidate passed for |
| `score` | integer 0-100 | screener score |
| `matched_skills` | list of strings | job-related skills only |
| `justification` | string | one sentence, job-related criteria only (skills, experience, projects); never personal traits |
| `screened_at` | ISO 8601 datetime with offset | when screening ran |

Rules: the scheduler never changes these records and never decides who is invited. HR invites a passed candidate
from the dashboard; only then does the candidate's signed booking link work.
