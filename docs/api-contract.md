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

## Internal service contracts

### Drafter (`services.drafter`)

The drafter has no HTTP endpoint. The orchestrator calls it in-process, and it never sends or records anything.

| Function | Input | Output |
|---|---|---|
| `draft_node(state, deps=None)` | `state["draft_request"]`: a `DraftRequest` | `{"draft_result": DraftResult}` as JSON-compatible data |
| `redraft(request, feedback, revision, deps=None)` | `DraftRequest`, recruiter feedback, revision number from 1 | `DraftResult` |
| `recheck_edited_draft(proposal, edited_subject, edited_body, context, config=DEFAULT_CONFIG)` | `ProposedAction`, recruiter's text, `DraftContext` | `DraftResult` |

#### `DraftRequest`

| Field | Type | Notes |
|---|---|---|
| `email` | `InboundEmail` | `email_id`, `thread_id`, `from_address`, `subject`, `body`, `received_at` |
| `thread_history` | `ThreadMessage[]` | `thread_id`, `from_address`, `direction` (`inbound` or `outbound`), `subject`, `body`, `sent_at`. Other threads and inbound messages from other senders are excluded |
| `recruiter_signature` | string | Trusted, supplied by the application |
| `approved_slots` | datetime[] | Recruiter-approved interview slots, optional |

#### Candidate record

`CandidateDirectory.find_by_email(email)` returns records. Only these fields are read; all others, such as scores or notes, are ignored:

`candidate_id`, `first_name`, `email`, `job_title`, `stage`, `documents_received`, `documents_missing`, `interview` (`scheduled_at`, `location`), and `decisions` (`type`, `decided_by`, `decided_at`, `details`).

Decision `type` is one of `advance`, `reject`, `offer`, `hire`, `salary`.

#### `DraftResult`

| Field | Type | Notes |
|---|---|---|
| `status` | string | `ready_for_review`, `needs_human`, or `quarantined` |
| `proposal` | `ProposedAction` or null | Set only when `status` is `ready_for_review` |
| `reason_code` | string or null | See the table below |
| `human_message` | string or null | Text for the reviewer. Display it as plain text |

#### `ProposedAction`

`action_type` (`send_email`), `candidate_id`, `to`, `subject`, `body`, `in_reply_to`, `intent`, `claims` (`text`, `source_field`), `warnings`, `payload_hash`, `idempotency_key`, `revision`, `prompt_version`.

`to`, `in_reply_to`, and `candidate_id` never come from the LLM. `payload_hash` is the SHA-256 of canonical JSON of `to`, `subject`, `body`, and `in_reply_to`. `idempotency_key` is a stable hash of `email_id`, `candidate_id`, and `revision`.

#### Reason codes

| Code | Status | Meaning |
|---|---|---|
| `invalid_request` | `needs_human` | The request failed validation |
| `candidate_lookup_unavailable` | `needs_human` | No candidate directory is wired in, or it failed |
| `unknown_sender` | `needs_human` | The sender matches no candidate |
| `ambiguous_sender` | `needs_human` | The sender matches several candidates |
| `invalid_candidate_record` | `needs_human` | The record failed validation |
| `injection_suspected` | `quarantined` | The detector flagged the input |
| `phishing_suspected` | `quarantined` | The email has strong warning signs of phishing. `human_message` names them |
| `llm_unavailable` | `needs_human` | No LLM client is wired in |
| `llm_failed` | `needs_human` | The LLM failed and no fallback could be used |
| `llm_escalated` | `needs_human` | The model asked for human input |
| `unsupported_language` | `needs_human` | The language is not configured |
| `format_invalid` | `needs_human` | HTML, control characters, empty text, length, or a line break in the subject |
| `unsupported_url` | `needs_human` | A URL is not in the context or allowlist |
| `unsupported_email` | `needs_human` | An email address is not in the context or allowlist |
| `undecided_outcome` | `needs_human` | The draft implies an outcome with no recorded human decision |
| `internal_data` | `needs_human` | The draft mentions scores, internal notes, or protected attributes |
| `unsupported_amount` | `needs_human` | A money amount is not in the context |
| `unsupported_date` | `needs_human` | A date, time, or relative date is not supported |
| `unsupported_phone` | `needs_human` | A phone number is not supported |
| `unsupported_number` | `needs_human` | A number is not supported |
| `claim_unsupported` | `needs_human` | A claim is missing, not backed by its cited field, or not reflected in the draft |
| `contradicts_record` | `needs_human` | The draft says nothing more is needed while documents are still missing |
| `revision_limit_reached` | `needs_human` | Too many redrafts |
| `internal_error` | `needs_human` | An unexpected error occurred |

#### Requirements on the orchestrator and executor

- Send only the approved text, and only when its hash matches `payload_hash`.
- Use `idempotency_key` to prevent duplicate sends.
- Record the approver.
- Check for newer emails in the thread before sending.

`Orchestrator` in `backend/orchestrator/graph.py` and `execute_approved` in `backend/core/executor/executor.py` implement these requirements.

### Orchestrator (`orchestrator.graph.Orchestrator`)

Gateway routes should call these methods rather than the graph, queue, or executor directly.

| Method | Purpose |
|---|---|
| `start(subject_id, task="draft_reply")` | Start a task. Calling it again returns the current state, without drafting or sending again |
| `resume(thread_id, decision)` | Give a person's decision to a paused workflow. Raises `ApprovalError` if it is not paused |
| `view(thread_id)` | Read a workflow's current state |
| `diagram()` | Return the graph as a Mermaid diagram |

`start` also accepts `task="triage_email"`, which classifies the email first and drafts a reply only for routine questions from candidates, and `task="daily_digest"` with `all` or a date as the subject, which builds a digest. `digest(scope)` reads the latest one. `paused_thread_for_email(email_id)` finds the paused workflow holding an email's draft, whichever task started it.

`start`, `resume`, and `view` return a `WorkflowView` with `thread_id`, `status`, `waiting_for_human`, `approval_id`, `payload_hash`, `reason_code`, `message`, `result`, and `classification`. Show the reviewer the draft by reading `approval_id` from the queue. `classification` has `type`, `urgency`, `needs_human`, `can_draft`, `sender_kind`, and `rules_applied`, and is set only for triage.

| `decision` | Required fields |
|---|---|
| Approve and send | `action: "approve"`, `reviewer`, `reviewed_hash` (the `payload_hash` the reviewer saw) |
| Edit, which then needs approval | `action: "edit"`, `reviewer`, `subject`, `body` |
| Redraft | `action: "redraft"`, `reviewer`, `feedback` |
| Reject | `action: "reject"`, `reviewer` |

An invalid decision pauses the workflow again with an explanation in `message`, and changes nothing. The gateway must authenticate the reviewer and set `reviewer` itself, rather than trusting a value from the client.

Workflow statuses are `awaiting_review`, `sent`, `rejected`, `needs_human`, `quarantined`, `new_application`, `no_action`, `stale`, `send_failed`, `refused`, `completed`, and `not_started`.

Queue statuses are `pending`, `approved`, `rejected`, `superseded`, `sending`, `sent`, `stale`, and `send_failed`.

### Daily digest (HR token required)

| Route | Purpose |
|---|---|
| `POST /api/hr/digest/generate` with `{"date": "YYYY-MM-DD"}` or `{}` | Start building a digest for a day or the whole inbox. Returns 202. Returns 409 if one is already running, and 422 for an invalid date |
| `GET /api/hr/digest?date=YYYY-MM-DD` | Read `scope`, `job` (`state`: `idle`, `running`, `done`, or `failed`), and `digest` (null if there is none yet), and `saved` (periods with a saved digest, most recently generated first) |

`digest` has `scope`, `generated_at`, `total`, `counts`, `urgency`, `headline`, `needs_answer`, and `groups`. Each group has `type`, `label`, `total`, `urgency`, and `items`. Each item has `email_id`, `thread_id`, `sender`, `subject`, `summary`, `summary_source`, `received_at`, `type`, `urgency`, `needs_human`, `can_draft`, `sender_kind`, `rules_applied`, `workflow_status`, and `bucket`.

### LLM client (`core.llm`)

`get_llm_client()` returns a client with `complete_json(*, system, user, json_schema, timeout_s)`. Other services can use `generate_structured(client, schema, *, system, user, timeout_s)` to get a validated Pydantic object. The model comes from `LLM_MODEL`, and the local Ollama address from `LLM_HOST`. Failures raise `LLMError`, which holds only a short code.
