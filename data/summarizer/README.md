# Summarizer Test Emails

192 fictional HR emails for testing the daily digest and the inbox, from a few lines to about 3,600 words. All people, companies, and addresses are invented.

## Try them in the website

Start the gateway with these two settings, then open the Digest page at `/hr/digest`. Your normal demo inbox and its drafts are not changed.

```bash
export HIREWALL_DATA_DIR="$PWD/data/summarizer"
export HIREWALL_RUNTIME_DIR="$PWD/.runtime/summarizer-demo"
```

Generating the whole inbox takes about 15 minutes on a local model, because every email is read. For a quick try, pick one day from 2026-11-02 to 2026-11-06, which takes about 3 minutes. Results are saved, so a second run is fast.

## What is in the set

There are 55 hand-written emails, each with longer versions of the same message, so the same request can be tested at every length.

| Type of email | What makes it hard |
|---|---|
| Original | The hand-written email, with traps such as declining an offer after long thanks, or deciding not to withdraw |
| `signature` | A signature, phone number, link, and legal notice |
| `thread`, `long_thread` | Older messages quoted under the new one |
| `background` | Long background before the real request |
| `over_limit` | The request starts more than 6,000 characters in |
| `huge_end` | About 15,000 characters, with the new message under the quoted history |
| `huge_middle` | About 17,000 characters, with the message between pasted text and quoted history |
| `huge_pasted` | About 19,000 characters of pasted text around the message, too long for the model to read in full. It must reach a person and be marked as partly read |

The set also includes phishing, prompt injection, newsletters, and automatic replies. Because of the longer versions, the same sender and subject appear several times in the digest.

## Files

| File | Use |
|---|---|
| `emails/inbox.json` | The emails |
| `expected.json` | For each email, the correct type, urgency, and main point. `tune` emails may be used to improve the agent. `holdout` emails are only for the final score |
| `candidate_status.json` | The fictional candidates who sent them |

`scripts/generate_summarizer_data.py` rebuilds this folder. `scripts/evaluate_summarizer.py` scores the digest against the labels.

## Results

Hold-out emails, which were never used to change the agent: 78 emails from 22 families, run twice on the local model `qwen3.5:4b`. Tune results are shown for comparison because the fixes were made against them.

| Measure | Hold-out | Tune |
|---|---|---|
| Digest has the main point | 87% | 96% |
| Subject line alone has the main point | 89% | 66% |
| First 20 words have the main point | 33% | 25% |
| Digest has the main point and the key detail | 73% | 82% |
| Subject line alone has both | 37% | 34% |
| First 20 words have both | 21% | 12% |
| Email words per digest line words | 105 to 1 | 104 to 1 |
| Attack text repeated in a summary | 0 | 0 |
| Results that needed a person but went to the drafter instead | 2 of 92 | 1 of 72 |
| Model failures | 0 | 0 |

Time per email was about 4 seconds for short emails and 6 seconds for the longest.

### Limits

- The emails and labels were written by the same author, so these numbers are not an independent test. Scores come from phrase matching, which cannot see a wrong meaning.
- The subject line ties the digest on the main point in hold-out, because those subjects are very informative. The digest's gain there is the key detail, and requests buried in long emails with vague subjects.
- Across two runs, 58% of hold-out summaries were word for word the same. The main point result changed on 2 emails.
- Some summaries miss the main point. For example, `s-131` says a sender asks to stop looking for a transcript, but not that they are withdrawing. Open an email before acting on it.
- Emails too long for the model to read in full can get a wrong summary. They are marked "Partly read, so open it" and always go to a person.
- The evaluation's gate is not passed, because of the misses in the table. In all three, the email was marked ready to draft, so any reply still needs human approval. `s-091` is a polite prompt injection that the detector did not catch, though its summary did not repeat the attacker's claim.
