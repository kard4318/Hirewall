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
from the dashboard; only then does the candidate's signed booking link work. A candidate shortlisted in the screener
is added to these records and invited once a person approves it (`ScreenerHandoff`), under the id
`<candidate_id>--<job_id>`. Rejecting them removes the invitation, unless they already have a booking.

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

Queue statuses are `pending`, `approved`, `rejected`, `superseded`, `sending`, `sent`, `stale`, `send_failed`, `recorded`, and `record_failed`.

### Screener (`services.screener`)

The screener is one service with one public facade, `ScreeningService` (`services/screener/service.py`). It reads
resumes, scores candidates against a job and explains each score. It never shortlists, rejects or contacts anyone:
a recruiter proposes a decision, a human approves it in the approval queue, and only `core/executor` records it.
It uses only `core/` and `security/`, and runs alone with `python scripts/demo_screener.py`.

Every output identifies a candidate by a pseudonymous `candidate_id` (`cand-` and 12 hex characters of the
resume's content hash). Name, contact details, profile links and protected attributes are split off at ingestion,
stored apart, and never reach the scoring code, the model, logs or audit events.

| Method | Input | Output |
|---|---|---|
| `ingest_files(files)` | list of `(filename, bytes)`, at most 20 | `IngestionTask` (runs in the background; poll `get_task`) |
| `load_demo()` | none | `IngestionTask` loading the fictional set in `data/resumes/` |
| `get_task(task_id)` | id | `IngestionTask` |
| `list_candidates()` | none | `CandidateSummary[]`, sorted by `candidate_id` |
| `list_jobs()` / `get_job(job_id)` | none / id | `JobOffer[]` / `JobOffer` |
| `create_job(title, requirements)` | `JobOffer` fields without `job_id` | `JobOffer` |
| `start_run(job_id)` | id | `ScreeningRun` with status `queued` |
| `execute_run(run_id)` | id | `ScreeningRun` with status `done` or `failed`; saves progress after each candidate |
| `get_run(run_id)` | id | `ScreeningRun` plus recorded `statuses` |
| `prepare_proposal(run_id, candidate_ids, kind)` | `kind` is `shortlist` or `rejection` | `proposal_id` |
| `build_proposed_action(proposal_id)` | id | `ProposedRecordAction` as JSON-compatible data |
| `reveal_identity(candidate_id, reviewer)` | id, the authenticated reviewer | `Identity`; writes a `screener.identity_revealed` audit event |
| `extract_posting(filename, data)` | an offer document | `(IngestionTask, job_id)`; makes a draft in the background |
| `get_posting(job_id)` / `list_postings()` | id / none | `JobPosting` / `JobPosting[]` |
| `update_posting(job_id, details)` | id, `JobPostingDetails` | `JobPosting`; drafts only, requirements derived again |
| `publish_posting(job_id)` / `close_posting(job_id)` | id | `JobPosting` |
| `list_applications(job_id)` | id | application rows with the candidate summary and merged flags |
| `get_extracted(candidate_id)` | id | profile, sections and flags, pseudonymous |

Errors raise `ScreenerError` with a short code: `job_not_found`, `run_not_found`, `task_not_found`,
`candidate_not_found`, `proposal_not_found`, `no_candidates`, `unknown_candidate`, `empty_selection`,
`run_not_finished`, `no_requirements`, `posting_draft`, `posting_published`, `posting_closed`, `job_closed`, `try_later`.

`start_run` scores only the job's applicants if it has any, otherwise the whole pool. `list_jobs` returns samples,
presets, hand-written jobs and published postings. `get_job` also resolves closed postings, so their runs stay readable.

#### `JobOffer`

| Field | Type | Notes |
|---|---|---|
| `job_id` | string | from `data/job_offers/*.json`, or `job-` and 8 hex characters for a created job |
| `title` | string | trusted, written by a recruiter |
| `requirements` | `{text, kind}[]` | at least one; `kind` is `required`, `preferred` or `responsibility`. A line such as "3+ years of experience" sets the experience requirement |

#### Candidates CSV

Columns, with common spellings accepted: `name`, `email`, `cv` (required), `cover_letter`. Comma, semicolon or tab, up to
100 rows. A `cv` or `cover_letter` cell ending in `.pdf` or `.docx` is a file uploaded in the same request, matched by base
name; any other value is the document's text. Nothing is read from a path on disk. Results are per row: `index` is the row,
and `reason_code` can be `cv_missing`, `cv_file_missing`, `cover_letter_file_missing` or `cover_letter_needs_posting`. A cover
letter is kept only when a posting is selected, because it belongs to an application.

#### `JobPosting`

| Field | Type | Notes |
|---|---|---|
| `job_id` | string | `job-` and 8 hex characters |
| `status` | string | `draft`, `published`, `closed` |
| `details` | `JobPostingDetails` | below |
| `requirements` | `{text, kind}[]` | derived in code from `details`, deduped, at most 40 |
| `extraction_failed` | boolean | the model failed: HR fills in the draft by hand |
| `flagged_requirements` | string[] | lines naming a protected attribute. They are not dropped: HR decides |
| `injection_excerpts` | string[] | lines removed from the document, hidden ones prefixed `[hidden] ` |
| `hidden_text_removed` | boolean | |
| `source_hash`, `created_at`, `published_at` | string | |

`JobPostingDetails`: `title` (required), `company`, `contract_type` (`internship`, `full_time`, `part_time`,
`fixed_term`, `freelance`, `other`), `location`, `remote` (`onsite`, `hybrid`, `remote`), `duration`, `start_date`,
`department`, `summary`, `responsibilities`, `required_skills`, `preferred_skills`, `min_years_experience`,
`education_level`, `languages`, `benefits`, `application_deadline`.

Requirements: `min_years_experience` gives "At least N years of experience" (`required`), `required_skills` and
`preferred_skills` give "Experience with X", and `responsibilities` are used as written.

#### `Application`

| Field | Type | Notes |
|---|---|---|
| `application_id` | string | stable for one job and candidate. The first application wins |
| `job_id`, `candidate_id` | string | one CV applying to two jobs is one candidate with two applications |
| `cover_letter` | `CoverLetterProfile` or null | display only, never scored |
| `cover_letter_text` | string or null | pseudonymized letter, at most 8,000 characters |
| `cover_letter_failed` | boolean | |
| `injection_excerpts`, `hidden_text_removed` | | from the letter, and they stay with this application |
| `submitted_at` | string | |
| `source` | string | `applicant` or `hr_upload` |

`CoverLetterProfile`: `motivation_summary`, `skills_mentioned`, `relevant_experiences`, `availability`, `start_date`,
`desired_duration`, `languages`, `mobility`.

#### `IngestionTask`

| Field | Type | Notes |
|---|---|---|
| `task_id` | string | |
| `status` | string | `queued`, `running`, `done`, `failed` |
| `total`, `done` | integer | files to process, files processed |
| `files` | `FileResult[]` | one per file, in upload order |

`FileResult`: `index` (position in the upload), `status` (`accepted`, `duplicate`, `rejected`, `failed`),
`reason_code` (for example `file_too_large`, `bad_signature`, `encrypted_pdf`, `too_many_pages`, `zip_bomb`,
`no_text`), `candidate_id`, `injection_flag`, `hidden_text_removed`, `extraction_failed`. File names are never
stored or returned, because they often contain the candidate's name.

#### `CandidateSummary`

`candidate_id`, `source` (`upload` or `demo`), `profile` (display family, below), `current_title`, `skills`,
`injection_flag`, `hidden_text_removed`, `extraction_failed`.

#### `ScreeningRun`

| Field | Type | Notes |
|---|---|---|
| `run_id`, `job_id` | string | |
| `status` | string | `queued`, `running`, `done`, `failed` |
| `total`, `done` | integer | candidates to score, candidates scored |
| `pending` | string[] | `candidate_id`s not scored yet (grey moons in the UI) |
| `candidates` | `RankedCandidate[]` | the scored candidates so far, ranked |
| `as_of` | date | fixed reference date for "present" in resumes (`SCREENER_AS_OF`) |
| `weights_config` | object | configured weights before renormalization |
| `required_years` | number or null | parsed from the job |
| `semantic_model_id`, `llm_model`, `rubric_prompt_version` | string | to reproduce the run |
| `reason_code` | string or null | set when `failed` |
| `statuses` | object | `get_run` only: `candidate_id` → `shortlisted` or `rejected`, as recorded by the executor |

#### `RankedCandidate`

| Field | Type | Notes |
|---|---|---|
| `candidate_id`, `rank` | string, integer | ranks start at 1 |
| `total_score` | number 0..1 | weighted mean over the criteria that apply |
| `scores` | object | `semantic`, `rubric`, `experience`, `graph`: each 0..1 or null (not applicable) |
| `applied_criteria` | string[] | criteria with a score and a positive weight |
| `weights_used` | object | weights renormalized over `applied_criteria`, summing to 1 |
| `matched_skills`, `missing_skills` | string[] | job skills found or not found in the resume (taxonomy names) |
| `additional_skills` | string[] | display only, never scored |
| `experience` | object | `relevant_years`, `total_years`, `required_years`, `score`, `positions_dated`, `positions_relevant`, `explanation` |
| `rubric` | object | `score`, `skills_coverage`, `related_experience`, `field_closeness` (integers 0-10), `skills_text`, `experience_text`, `field_text`, `reason_code`, `prompt_version` |
| `requirements_met`, `requirements_total` | integer | semantic requirements met |
| `evidence` | object[] | per requirement: `requirement`, `kind`, `score`, `raw_similarity`, `best_chunk_id` |
| `evidence_chunks` | object[] | `chunk_id`, `text`: the resume lines cited in `evidence` |
| `injection_flag` | boolean | carried through for the reviewer; never filters a candidate or changes a score |
| `injection_excerpts` | string[] | the offending lines, at most 300 characters each, hidden ones prefixed `[hidden] ` |
| `hidden_text_removed` | boolean | invisible text (white, tiny, off-page, hidden runs) was dropped at ingestion |
| `profile` | string | display only: `Backend`, `Data`, `Frontend`, `DevOps / Cloud` or `Other` |

Scoring rules:
- `semantic` is `SemanticIndex` unchanged. `experience` counts dated, job-relevant positions against the job's
  required years and is null when the job states none. `rubric` is the mean of the three model sub-scores divided
  by 10; the model never gives a total. `graph` is null until a graph scorer exists.
- Default weights: semantic 0.35, rubric 0.45, experience 0.20, graph 0 (`SCREENER_WEIGHT_*`).
- Null criteria are left out and the remaining weights renormalized. Order is total, then semantic score, then
  `candidate_id`, so two runs over the same data give the same ranking.
- The rubric prompt holds the job and the pseudonymized profile only. On a model failure the rubric is null with
  `reason_code` `llm_failed` or `invalid_output`, and the candidate is still ranked.
- Lines flagged as injection are removed from the text given to the model and the embedder, and kept as excerpts
  for the reviewer.
- `profile` is the taxonomy family that dominates the candidate's skills (backend and database, data, frontend,
  devops and cloud; generic categories ignored; ties broken in that order). It never changes a score.

#### `Identity`

`candidate_id`, `full_name`, `emails`, `phones`, `links`, `other` (removed address and protected-attribute lines),
`contacts` (`reference_id`, `job_id`, `full_name`, `email`, `consent_at` per form submission). Returned only by
`reveal_identity`. Form contacts never replace what was found in the CV.

#### `ProposedRecordAction`

| Field | Type | Notes |
|---|---|---|
| `action_type` | string | `record_shortlist` or `record_rejection` |
| `payload` | object | `job_id`, `run_id`, `candidate_ids` (sorted, unique) |
| `in_reply_to` | string | scope key `<action_type>:<proposal_id>`, so proposals for different candidates all stay pending |
| `payload_hash` | string | `action_hash(action_type, payload)`: SHA-256 of canonical JSON of `{"action_type", "payload"}` |
| `idempotency_key` | string | the `proposal_id`: a stable hash of `action_type`, `job_id`, `run_id` and `candidate_ids` |

Nothing in it comes from the model or from resume text.

#### Shortlist and rejection approval

1. The recruiter selects candidates in a finished run. `prepare_proposal` checks they belong to the run.
2. The gateway calls `Orchestrator.start(proposal_id, task="propose_shortlist")`.
3. The workflow builds the `ProposedRecordAction`, submits it to the approval queue, audits `approval.submitted`,
   and pauses at review.
4. A recruiter decides through `POST /api/hr/approvals/{approval_id}/decision`. The gateway sets `reviewer`.

| `decision` | Required fields | Effect |
|---|---|---|
| Approve | `action: "approve"`, `reviewer`, `reviewed_hash` | the queue approves only if the hash matches; then `core/executor.execute_record` re-checks the hash, claims the item once, writes `CandidateStatusStore`, audits `executor.outcome`, and tells each candidate whose status changed |
| Reject | `action: "reject"`, `reviewer` | nothing is recorded |

After approval, a rejection sends a fixed email with no score or reason, and a shortlist hands the candidate to the
scheduler, whose bot invitation goes by email. The address is the first one found in the CV, then the one typed in the
form. Delivery follows `EMAIL_MODE`: `outbox` keeps messages locally, and `smtp` sends them. Each candidate gets an
`executor.notification` audit event with `outcome`: `sent`, `outbox`, `no_email`, `in_progress` or `failed`. A failed
message never undoes the decision and is not retried.

`edit` and `redraft` do not apply and pause the workflow again with a message. Workflow and queue statuses add
`recorded` and `record_failed`.

#### HTTP endpoints

All these routes need an HR token (`Authorization: Bearer ...`). Errors are `{"detail": "<code>"}` with a short
code and never echo client input.

| Method and path | Body | Response |
|---|---|---|
| `POST /api/screener/candidates` | multipart `files`: 1-20 PDF or DOCX files, 5 MB each, or one CSV with the files it names; optional `job_id` of a posting to attach them to | `202 {task_id}`; `429 too_many_uploads` above 10 uploads a minute; `422` with `csv_no_cv_column`, `csv_empty`, `csv_too_many_rows`, `csv_too_large`, `csv_unreadable` or `one_csv_only` |
| `GET /api/screener/tasks/{task_id}` | | `IngestionTask` |
| `GET /api/screener/candidates` | | `{candidates: CandidateSummary[]}` |
| `POST /api/screener/candidates/demo` | | `202 {task_id}` |
| `GET /api/screener/jobs` | | `{jobs: [...]}`: `JobOffer` fields plus `status` (null if not a posting) and `application_count`, including draft and closed postings |
| `POST /api/screener/jobs/extract` | multipart `file` | `202 {task_id, job_id}`; poll the task, then read the draft |
| `GET /api/screener/jobs/drafts/{job_id}`, `GET /api/screener/jobs/{job_id}/posting` | | `JobPosting` |
| `PUT /api/screener/jobs/{job_id}` | `JobPostingDetails` | `JobPosting`; `409 posting_published` or `posting_closed` if not a draft |
| `POST /api/screener/jobs/{job_id}/publish` | | `JobPosting`; `409 no_requirements` |
| `POST /api/screener/jobs/{job_id}/close` | | `JobPosting` |
| `GET /api/screener/jobs/{job_id}/applications` | | `{applications: [...]}`, pseudonymous |
| `GET /api/screener/candidates/{candidate_id}/extracted` | | profile, sections and flags, pseudonymous |
| `POST /api/screener/jobs` | `{title, requirements: [{text, kind}]}` | `201 JobOffer` |
| `POST /api/screener/jobs/{job_id}/runs` | | `202 {run_id}` |
| `GET /api/screener/runs/{run_id}` | | `ScreeningRun` |
| `POST /api/screener/runs/{run_id}/shortlist-proposals` | `{candidate_ids: string[], kind: "shortlist" or "rejection"}` | `201 {proposal_id, approval_id, thread_id, payload_hash, status}` |
| `GET /api/screener/candidates/{candidate_id}/identity` | | `Identity`; audited |
| `GET /api/hr/approvals?status=` | | `{delivery, items: [{approval_id, status, action_type, thread_id, payload_hash, summary, notifications, created_at, decided_by, decided_at}]}`; `summary` and `notifications` hold IDs and outcomes only |
| `POST /api/hr/approvals/{approval_id}/decision` | `{action: "approve" or "reject", reviewed_hash}` | `WorkflowView` |
| `GET /api/hr/audit-log?limit=` | | `{entries: [...], verified: boolean}`, newest first, IDs only |

### Daily digest (HR token required)

| Route | Purpose |
|---|---|
| `POST /api/hr/digest/generate` with `{"date": "YYYY-MM-DD"}` or `{}` | Start building a digest for a day or the whole inbox. Returns 202. Returns 409 if one is already running, and 422 for an invalid date |
| `GET /api/hr/digest?date=YYYY-MM-DD` | Read `scope`, `job` (`state`: `idle`, `running`, `done`, or `failed`), and `digest` (null if there is none yet), and `saved` (periods with a saved digest, most recently generated first) |

`digest` has `scope`, `generated_at`, `total`, `counts`, `urgency`, `headline`, `needs_answer`, and `groups`. Each group has `type`, `label`, `total`, `urgency`, and `items`. Each item has `email_id`, `thread_id`, `sender`, `subject`, `summary`, `summary_source`, `received_at`, `type`, `urgency`, `needs_human`, `can_draft`, `sender_kind`, `rules_applied`, `workflow_status`, and `bucket`.

### LLM client (`core.llm`)

`get_llm_client()` returns a client with `complete_json(*, system, user, json_schema, timeout_s)`. Other services can use `generate_structured(client, schema, *, system, user, timeout_s)` to get a validated Pydantic object. The model comes from `LLM_MODEL`, and the local Ollama address from `LLM_HOST`. Failures raise `LLMError`, which holds only a short code.
