# Employee Q&A Service

Northwind Labs knowledge assistant: answers employee policy questions **only** from company documents, cites the
exact sections it used, and says "I don't know" (offering to pass the question to the People Team) instead of guessing.
It runs on a **local model through Ollama**: no cloud API, no paid key.

## Inputs / Outputs

- Input: a question, the asker's audience (`employee` or `hr`) and a mode (`auto` | `full` | `retrieval`).
- Output (`models.Answer`): `kind` (answered | not_found | refused_personal | sensitive | blocked | error), `answer`,
  `citations` (section id, title, version), `topic`, `mode`, `escalation_offered`, and an operator `notice`
  (for example "start Ollama") that is never part of the policy answer.
- Corpus: `data/hr_documents/*.md` with front matter (`doc_id`, `title`, `audience`, `version`, `effective_date`,
  `topic`, optional `supersedes`) and numbered headings (`## 1.` / `### 1.1`). Section ids look like `leave-policy#1.1`.

## Pipeline

1. **Pre-checks, no LLM** (`prechecks.py`): injection patterns give `blocked`; someone else's pay or leave, or the
   asker's own personal records, give `refused_personal` (pointing to the People Portal / People Team); sensitive
   topics such as harassment or mental health give `sensitive`, a fixed supportive reply with a private contact.
2. **Access filter first** (`access_control.py`): employees only ever get `audience: everyone` sections. HR-only text
   never reaches retrieval, prompts, citations or answers. Superseded documents are excluded at ingest for everyone.
3. **Context strategy** (`retriever.py`), chosen automatically:
   - `FULL_CONTEXT`: every accessible section, when the estimated tokens fit `FULL_CONTEXT_TOKEN_BUDGET` (3000).
   - `RETRIEVAL`: pure-Python BM25, top `RETRIEVAL_TOP_K` (5) sections scoring at least `BM25_MIN_SCORE` (4.5).
     Below the minimum nothing is selected and the LLM is **not called** (`not_found`).
4. **LLM call** (`answerer.py`, `prompts/answer.md`): sections wrapped as `<section id= title= version=>` inside
   `<documents>`, the question inside `<employee_question>`; both are declared data, never instructions. Strict JSON
   `{answerable, answer, citations, topic}` validated with Pydantic (one retry with the validation error).
5. **Code validation**: citations must be supplied section ids (invented ones dropped; none left gives `not_found`);
   emails and URLs in the answer must appear in the cited sections; the answer may not name documents the asker cannot
   read; at most 5 sentences / 900 characters. Any LLM failure (Ollama down, model missing, timeout, bad JSON) becomes
   a safe `error` answer that offers escalation; the conversation never crashes.
6. **Audit** (`audit.py`): kind, topic, mode, cited section ids, audience, reason code, latency and prompt tokens.
   Never the question or answer text (the in-memory adapter rejects any other field).

Defence in depth for documents: sentences that read like instructions to an AI are replaced at ingest with
`[instruction-like text removed]` (see the test trap `data/hr_documents/traps/office-tips.md`).

## Run it with Ollama

```powershell
ollama pull qwen3.5:4b            # or any local model
# .env: LLM_PROVIDER=ollama, LLM_MODEL=qwen3.5:4b (optional: OLLAMA_HOST, LLM_NUM_CTX, LLM_TIMEOUT_SECONDS, LLM_THINK)
python scripts\ask_knowledge.py --audience employee
python scripts\eval_knowledge.py --limit 8
```

Offline (no Ollama): add `--llm fake` to either script. The fake is a deterministic extractive model that quotes the
best-matching sentences, so the whole pipeline runs and can be evaluated without a GPU.

## How to test alone

```powershell
python -m pytest backend\services\employee_qa\tests backend\tests\test_core_llm.py
python scripts\eval_knowledge.py --llm fake          # writes data\runtime\eval_report.md
python scripts\eval_knowledge.py --calibrate         # BM25 score separation on the eval set
```

## Owner

TBD
