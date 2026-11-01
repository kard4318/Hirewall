# Summarizer Service

Classifies and summarizes the recruiter inbox. The classifier is built. The daily digest in `digest.py` is not built yet.

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

## Owner

TBD
