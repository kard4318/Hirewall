# Summarizer Service

Classifies and summarizes the recruiter inbox: the classifier labels each email, and the daily digest groups them by type and urgency.

## Classifier

It labels each email and writes nothing. The model suggests a label, and code decides what that label is allowed to do.

```python
from services.summarizer.node import classify_node

output = classify_node({"email": email})  # {"classification": {...}}
```

### Inputs / Outputs

The input email has `email_id`, `thread_id`, `from_address`, `subject`, `body`, and `received_at`.

| Output field | Meaning |
|---|---|
| `type` | One of the types below |
| `urgency` | `high`, `normal`, or `low` |
| `needs_human` | A person must decide or answer |
| `can_draft` | The drafter may try a reply. The draft still needs approval |
| `sender_kind` | `candidate`, `employee`, or `unknown`, from the sender's address only |
| `reason_code` | Why code decided without the model, such as `injection_suspected` or `llm_failed` |
| `reason` | One sentence from the model. Display it as plain text, because the sender can influence it |
| `rules_applied` | Which code rules changed the model's suggestion |

Types are `new_application`, `candidate_question`, `interview_scheduling`, `document_submission`, `decision_or_feedback`, `compensation`, `withdrawal`, `employee_question`, `automatic_reply`, `unrelated`, `suspicious`, and `unclassified`. Only code can assign the last two.

### What code enforces

| Rule | Why |
|---|---|
| The sender's kind comes from their address | An email cannot claim to be from a candidate or employee |
| Only a candidate can get a candidate type or `can_draft` | A stranger cannot reach the drafter |
| The model can raise `needs_human`, but cannot lower it for sensitive types | A manipulated model cannot hide an email |
| Pay, contract, complaint, and similar topics always reach a person | This does not depend on the model noticing them |
| A stranger's "unrelated" email about candidates, records, or files, or claiming authority, reaches a person | Impersonation is not silently dropped |
| A stranger cannot be `high` urgency | Writing "URGENT" does not move an email up the queue |
| The injection detector runs first | A hit becomes `suspicious` with no model call |
| The phishing detector runs next | A strong match becomes `suspicious` with `phishing_suspected` and no model call. A weak match goes to a person |
| Any failure becomes `unclassified` and goes to a person | Nothing is lost when the model fails |

### Known limits

- Phrase rules can miss reworded requests and can flag harmless emails.
- A stranger's `unrelated` or `automatic_reply` email that matches no rule ends as `no_action`. The digest should still list these, so someone can spot a mistake.
- Attachments are not read, and only email text is classified.
- A candidate can still raise their own email's urgency by how they write.

### How to test alone

From `backend/`, these tests use a scripted model and need no Ollama:

```bash
python -m pytest services/summarizer/tests
```

To measure it on the real model, from the repo root:

```bash
python scripts/evaluate_classifier.py --split tune --runs 2
python scripts/evaluate_classifier.py --split holdout --runs 2
```

Keep the hold-out split for final checks. If you tune against it, it stops being a fair test, so add new emails to it.

## Daily digest

`digest.py` builds the spec's daily digest. It reads the inbox, sends nothing, and writes only its own files in `.runtime/digests/`. Each email gets:

| Part | Where it comes from |
|---|---|
| Labels | The email's inbox label if it was triaged, so both pages agree. Otherwise the classifier, with the result cached |
| Status | Read from the orchestrator each time, so an approval shows without rebuilding |
| One-line summary | The model, which sees only that email, never a candidate's file |

Emails are grouped by type, with urgency counts, and those needing a human answer are listed first. No email is left out, including `no_action` ones, so someone can spot a mistake.

Each email's `bucket` is `needs_answer`, `draft_waiting`, `quarantined`, `ready_to_draft`, `no_action`, or `handled`.

### What protects the summaries

| Rule | Why |
|---|---|
| Quarantined emails get a fixed notice written by code, with no model call | An attacker's text cannot shape what HR reads about it |
| Automatic replies, unrelated email, and unclassified email show their subject, with no model call | They do not need one, which saves time |
| A summary with a link, contact detail, prompt leak, or suspicious text is replaced by the subject | A manipulated model cannot put a phishing link in HR's digest |
| A summary with a number that is not in the email is replaced by the subject | An invented date or amount would look like a fact |
| The headline and counts are written by code | They cannot be wrong or shaped by an email |
| Model failures are not cached | The next run tries again |

Phone numbers and similar details in subjects and summaries are masked. Display summaries as plain text, because a sender can still influence the wording.

### Run it

```bash
python scripts/run_drafter_demo.py digest
python scripts/run_drafter_demo.py digest --date 2026-11-02
```

In the app, open **Digest** in the HR area. Filters by urgency and type work on the saved digest, so they never call the model.

The model reads up to 12,000 characters of an email. A longer email loses its quoted history first, then keeps its start and end. If it is still too long, the email goes to a person and its line starts with "Partly read, so open it". Code rules on sensitive topics read the whole email.

`python scripts/evaluate_summarizer.py --split holdout --runs 2` measures this on `data/summarizer`, where the results are recorded.

### Known limits

- A summary can still misdescribe an email in ordinary words, so HR should open the email before acting on it.
- A date uses the day in the email's own timestamp, not HR's time zone.
- A digest is generated when someone asks for it. Nothing schedules it yet.

## Owner

TBD
