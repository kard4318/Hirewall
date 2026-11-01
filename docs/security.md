# Security

Threat model, defenses (sanitizing, injection detection, PII/bias filtering) and the human-approval guarantee.

TODO

## Drafter

The drafter reads text written by outsiders, so it assumes the model can be manipulated. Its protections do not depend on the model refusing an attack.

### Defenses

| Threat | Defense |
|---|---|
| The model is told to send or contact someone else | The model has no tools and its output schema has no recipient fields. Code takes the recipient from the candidate record |
| A reply exposes another candidate's data | The candidate is found by exact sender address, and only that candidate's allowlisted fields reach the model |
| A reply exposes scores or notes | Those fields are never copied into the context, and the output is checked for internal terms |
| Hidden instructions | Hidden HTML, comments, zero-width characters, and Unicode tag characters are removed before the model sees the email. The reviewer gets a warning |
| Breaking out of the data block | The email is wrapped in a random per-request boundary, and that boundary is removed from the email text |
| Phishing or data exfiltration through links | URLs and email addresses must be in trusted data or an allowlist. Text in the candidate's email does not count |
| Invented facts | Dates, times, numbers, and phone numbers must have a source. Money amounts must be in trusted data |
| Decisions made by AI | Outcome and salary wording needs a matching human-recorded decision |
| Email header injection | Line breaks in the subject are blocked, including after a recruiter edit |
| Malformed model output | Output is strictly validated with one repair attempt, then falls back to a fixed template or a human |
| Sensitive data in logs | Logs and audit events hold only IDs, hashes, status, reason codes, prompt version, and latency |

### Phishing detection

`security/phishing_detector.py` checks each email for concrete warning signs, such as credential requests, dangerous attachments, payment changes, bulk personal data requests, and authority claims combined with secrecy. It works in three levels, and a known candidate's address does not excuse an email, because addresses can be forged or accounts taken over:

| Verdict | Score | What happens |
|---|---|---|
| `phishing` | 4 or more | Quarantined with reason `phishing_suspected`, with no model call. The warning signs are shown to HR |
| `suspicious` | 2 or 3 | The classifier sends it to a person, and the drafter adds a `phishing_signals` warning |
| `clean` | 0 or 1 | Handled normally |

To measure it, run `python scripts/evaluate_phishing.py --split tune` or `--split holdout`.

We tested the pretrained model `aamoshdahal/email-phishing-distilbert-finetuned` and did not use it. On our emails, its default threshold flagged 36% of 96 ordinary emails and caught 46% of 24 phishing emails, and it missed most HR-specific scams. It also states no license.

### Known limits

- **Sender identity:** the drafter trusts the `from_address` it receives. A forged sender matching a real candidate gets through, so the email integration must verify senders (SPF, DKIM, DMARC). The reply still goes only to the address on record.
- **Values from the candidate's email:** a date, time, phone number, or plain number that appears only in the candidate's email causes a reviewer warning, not a block. A recruiter must not approve such a value without checking it.
- **Phrase lists:** decision, internal-data, and contradiction checks use phrase lists, so a paraphrase can pass them. Numbers written as words are not detected. Because of this, the human review step remains essential.
- **Wrong but well-formed drafts:** a local model can state something false that no check recognizes. In testing it told a candidate no more documents were needed while one was missing, which led to the `contradicts_record` check. Other such errors can still reach the reviewer, so a recruiter must read every draft against its listed sources.
- **Invented details in ordinary words:** in testing the model told a candidate their interview would be "conducted with a panel", which no record said. Checks only recognize values such as dates, numbers, and links, so this kind of invention can reach the reviewer.
- **Unconfirmed promises:** phrases such as "we will be in touch shortly" only add a `promise_to_confirm` warning. A recruiter should remove any promise they do not intend to keep.
- **Rejection reasons:** the checks cannot detect an invented reason written in ordinary words.
- **Language:** the checks rely on the language the model reports, and only English is configured. A model that reports `en` while writing another language would avoid the phrase lists.
- **Other people's names:** names are not checked directly. The model only sees names from the context and the current thread.
- **Sender-influenced text:** `human_message` and `warnings` may include model text shaped by the sender, so they must be displayed as plain text.
- **Injection detector:** it uses patterns and is only a signal. Attacks can avoid it, and unusual ordinary text can trigger it, which only sends that email to a human.
- **Data sent to the model:** the model runs locally through Ollama. `core/llm` refuses any host other than this machine, so prompts are not sent to a cloud service. Anyone with access to this machine can still reach the local server, which has no authentication. Do not change `OLLAMA_HOST` to expose it on a network.
- **Model quality:** a small local model is more easily manipulated and makes more mistakes than a large hosted one. The code-level checks and human approval are what protect against this.

## Screener (resumes)

A resume is a file written by the person being judged, so the screener treats it as hostile. Scores are a
reading aid: the model has no tools, nothing is decided automatically, and every shortlist or rejection goes
through human approval.

### Defenses

| Threat | Defense |
|---|---|
| Malicious or disguised file | Only PDF and DOCX up to 5 MB. The real signature is checked (`%PDF-`, zip `PK`), not the extension. Encrypted PDFs and PDFs over 10 pages are refused |
| Zip bomb or crafted DOCX | Member count, total uncompressed size and compression ratio are capped before anything is read. Absolute or `..` member paths are refused |
| Hidden text (white, tiny, off-page, hidden runs) | Only visible text is extracted: PDF characters with a near-white fill, under 3 pt or outside the page are dropped, and so are DOCX runs that are vanished or white. `hidden_text_removed` tells the reviewer |
| Visible instructions to the model (EN, FR, AR) | Lines matching the injection patterns are removed from the text given to the model and the embedder, and shown to the reviewer as excerpts. `injection_flag` is set but never filters a candidate or changes a score |
| Instructions in hidden text | Removed with the hidden text. The hidden lines are still checked, so the candidate is flagged |
| Words split with zero-width characters | Invisible and format characters are removed before detection and scoring |
| Breaking out of the data block | The resume is wrapped in a random per-request boundary, removed from the resume text, and the system prompt says the block is data |
| The model is told to give a high score | The model only gives three integers against anchored scales and short evidence texts. Code computes the criterion and the total. Two other criteria do not involve the model |
| Keyword stuffing | Repeated lines are deduplicated before embedding, experience counts only dated positions, and skills outside the job never add to the score. See Known limits |
| Bias from identity | Name, contact details, profile links, photo, age, gender, nationality and date of birth are split off at ingestion and stored apart. The model, scores, logs and audit events see only a pseudonymous `candidate_id` |
| Unlogged identity access | Identity is returned only by an HR-authenticated endpoint that writes an audit event |
| Approving something else than what was reviewed | Shortlists and rejections are queued with a hash of the action. Approval needs that hash, the executor checks it again, and a claim makes it run once |
| Resume text in logs | Logs, audit events and workflow state hold IDs, hashes, statuses, reason codes and counts only. Upload file names are not stored |
| Poisoned job offer | An offer gets the same file checks, visible-text extraction and injection removal as a resume. Values the model returns are checked again, and nothing is public until HR has reviewed and published it |
| Discriminatory requirements | Lines naming age, gender, nationality, religion, family status, health or photo are listed for HR, who is asked to confirm before publishing. They are not silently dropped |
| Poisoned cover letter | The same checks and fencing as a CV. A letter is display only, so it cannot reach the ranking or the rubric. Its flags stay on that application |
| A stranger resubmitting someone's CV | A CV already on file keeps its identity and its first application. A later submission only adds a form contact that HR can see. The reference id is random, so the response does not reveal that the CV is known |
| Abuse of the public form | Rate limit and body size are checked before the body is read, separately from HR's limit. At most 20 applications wait for the model. The response holds only a reference id |
| Form contact details in prompts | Name and email go to the identity store only. They are used to mask the letter, and they are never sent to the model |

### Known limits

- **Name detection:** names are found in the resume header with a heuristic. A name written elsewhere in an unusual
  form can remain in the evidence text. Demo profiles with structured names are exact.
- **Hidden text:** text drawn over by an image, text in the same colour as a coloured background, and text inside
  images are not detected. Background is assumed to be white.
- **Patterns:** injection detection is a signal. A paraphrase can avoid it; the model's limited role and human
  approval are what protect the decision.
- **Model judgement:** a small local model can misread a resume. The rubric shows its evidence texts so a recruiter
  can check them, and the semantic and experience criteria do not depend on it.
- **Keyword stuffing:** a list of the job's skills can still raise the semantic score and may mislead the model. The
  same words written under a dated job make that job count as relevant experience, because relevance is judged by
  the words in the position. A recruiter should compare the evidence quotes with the score.
- **Public form:** there is no email check or CAPTCHA, so a form contact is unverified, and anyone can submit a copy of someone's CV. The rate limit is in memory and per client address, so behind a proxy all applicants share one limit.
- **Name in a CV:** the name typed in the form is not used to mask the CV, so CV masking still depends on the header heuristic.
- **Retention:** there is no way yet to delete an applicant's data or withdraw consent. Add one before using real data.
- **Protected-attribute lines:** these use a word list, so a paraphrase can pass and an ordinary sentence can be flagged. The list only asks HR to look.
- **Bias:** removing identity does not remove every proxy (school names, places, career gaps). Recruiters must not
  treat the ranking as a decision.

## Approval and sending

`core/executor` is the only code that sends or records. `execute_approved` sends emails and `execute_record` records
shortlists and rejections in the candidate status store, under the same approval, hash, claim and audit rules. It
enforces these rules for every send:

| Rule | How it works |
|---|---|
| A named human approved | The queue requires an approver, and the item must be `approved` |
| The approval covers this exact text | Approval requires the hash of the text the reviewer saw. An edit changes the hash, so an earlier review no longer applies. The hash is checked again just before sending |
| The recipient cannot change | Edits that change `to` or `in_reply_to` are refused |
| No duplicate replies | The item is claimed atomically, once, and only if no other reply to that email is sending or sent |
| The draft is still current | If a newer email arrived in the thread, the draft becomes `stale` and is not sent |
| Failures need a human | A failed send becomes `send_failed` and is never retried automatically, because the email may have gone out |
| A record exists | Each step goes to a hash-chained audit log of IDs and outcomes. `verify()` detects edited, removed, or reordered entries, but not removal of the newest entries |

### Known limits

- **Identity:** the queue records the approver's name but does not authenticate them. The gateway must do this with its login and roles.
- **Storage:** the queue, audit log, outbox, and workflow checkpoints are local files, and anyone with file access could replace them. Checkpoints hold IDs and outcomes, but a recruiter's edits, feedback, and short status messages from the model are saved there too.
- **Tracing:** do not turn on LangSmith tracing, for example with `LANGSMITH_TRACING`. It would send workflow data to a cloud service, which breaks the local-only guarantee.
- **Sending:** the email provider is a local outbox. A real provider needs its own credentials and tests.

## Shared security layer (`backend/security/`)

One screen for all untrusted text, so every service applies the same rules:

- `security.quarantine.screen_untrusted(text, source) -> Verdict` (`allow` | `flag` | `block`, reasons, model score).
  Used by the scheduler candidate chat and the knowledge assistant; `security.quarantine.is_suspicious` is a drop-in
  replacement for `security.injection_detector.is_suspicious` that also asks the model.
- `security.rules`: multilingual rules (EN/FR/AR), obfuscation folding (look-alikes, leetspeak, spaced letters,
  invisible characters) plus the `injection_detector` patterns.
- `security.injection_model`: local classifier `protectai/deberta-v3-base-prompt-injection-v2` (Apache-2.0), ONNX on
  CPU via onnxruntime, fully offline after `python scripts/download_security_models.py`.
- `security.pii_bias_filter`: `mask_pii` (emails, phones, IBAN, cards, URLs) and `strip_protected_attributes`
  (age, gender, nationality, religion, family status... lines) for screening.
- `security.output_validator.output_problems`: invisible characters, prompt leaks, unexpected emails or links.
- Quarantine: blocked and flagged inputs are appended to `data/runtime/quarantine.jsonl` with a hash, reasons, the
  model score and a PII-masked excerpt.

Policy: rules always run and block on their own. The model is a second opinion controlled by
`SECURITY_MODEL_MODE` (`off`, `monitor` = flag only, `block` = may block above `SECURITY_MODEL_THRESHOLD`).
If the model fails, the rules still apply. Neither replaces the design: models have no tools and humans approve
every action. Measure with `python scripts/eval_security.py` (report in `data/runtime/security_report.md`).
