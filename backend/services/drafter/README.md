# Drafter Service

Drafts email replies for human approval. It never sends or records anything.

The LLM has no tools and only returns structured text. Code finds the candidate, chooses what the LLM can see, sets the recipient, and checks the result.

```
resolve candidate -> build allowlisted context -> pre-check -> LLM draft -> validate -> checks -> proposal or escalation
```

## Inputs / Outputs

The full contract, including reason codes, is in [docs/api-contract.md](../../../docs/api-contract.md).

```python
from services.drafter.node import draft_node, recheck_edited_draft, redraft

output = draft_node({"draft_request": request})  # {"draft_result": {...}}
```

| Status | Meaning | `proposal` |
|---|---|---|
| `ready_for_review` | Passed all checks. Show it to the recruiter, including any `warnings` | Set |
| `needs_human` | No sendable draft. `reason_code` and `human_message` explain why | Null |
| `quarantined` | The injection detector flagged the input, so the LLM was not called | Null |

Display `human_message`, `warnings`, and draft text as plain text. Some of it can be influenced by the sender.

## Dependencies

`load_default_deps()` looks for these, and uses each one only if it exists:

| Module | Name | What it must provide | If missing |
|---|---|---|---|
| `core/llm/client.py` | `get_llm_client()` | An object with `complete_json(*, system, user, json_schema, timeout_s)`, returning a JSON string or mapping, and enforcing `timeout_s` | `llm_unavailable` |
| `core/db/repositories.py` | `get_candidate_directory()` | An object with `find_by_email(email)`, returning candidate records | `candidate_lookup_unavailable` |
| `security/injection_detector.py` | `is_suspicious(text)` | Returns a bool | Draft continues with an `injection_detector_unavailable` warning |
| `core/audit/audit_log.py` | `get_audit_sink()` | An object with `record(event, **fields)` | Only the log line is written |

## Changing behavior

- **Settings:** edit `config.py` for limits, approved link and email domains, and phrase lists.
- **Prompt:** add a new file in `prompts/` and update `prompt_version`.
- **New language:** add it to `supported_languages`, and add its decision and internal phrase lists and a translated fallback. Date checks only recognize English month and weekday names, so digits in other formats are treated as unsupported numbers.

## Owner

Aabchoun

## How to test alone

From `backend/`:

```bash
python -m pip install -r requirements.txt
python -m pytest services/drafter/tests
```

These tests run offline with a scripted LLM. Attack tests script a model that obeys the attacker, to show the code stops it.

To try the real local model once Ollama is running and `qwen3.5:4b` is downloaded:

```bash
python -m services.drafter.tests.live_eval --verbose
```

## Metrics

To measure the drafter on a labeled dataset, from the repo root:

```bash
python scripts/evaluate_drafter.py --data data/realistic --runs 2
```

The folder needs `candidate_status.json`, `emails/inbox.json`, and `expected.json`. Each `expected.json` item has `email_id`, `category`, `expected_status` (`ready_for_review`, `needs_human`, or `any_safe`), `must_mention`, and `must_not_say`. Results go to `.runtime/eval/<timestamp>/`, and nothing is queued or sent.

| Group | Metric | Target |
|---|---|---|
| Safety | Private data or attack text in a draft | 0 |
| Safety | Drafted when the label says a human should decide | 0 |
| Safety | Exact forbidden phrases found, to confirm by reading | Review each |
| Routing | Correct outcome, excluding `any_safe` emails | High |
| Routing | Good replies sent to a human unnecessarily | Low |
| Routing | Normal emails quarantined | Low |
| Quality | Required facts present in drafts | High |
| Reliability | Failures, template use, time per email, and consistency across runs | Failures 0 |
| Human review | Drafts usable with small edits | High |
| Human review | Drafts wrong but passing every check | 0 |

The command exits with an error, shown as `GATE: NEEDS ATTENTION`, on a leak, a draft a human should have decided, or a model failure.

Only a person can judge the two human review metrics. Open `review.csv` from the results folder, enter `y` or `n` under `usable` and `wrong`, save it as CSV, and score it without calling the model:

```bash
python scripts/evaluate_drafter.py --data data/realistic --score .runtime/eval/<timestamp>
```

Treat the labels as a starting point. An LLM wrote the realistic set's answer sheet, so a metric can fail because the label is wrong. Check the email before changing the drafter.

To run the whole flow on the fictional inbox, see `scripts/run_drafter_demo.py` and the root README.
