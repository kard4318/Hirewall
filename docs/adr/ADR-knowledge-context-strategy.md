# ADR: Context strategy for the knowledge assistant

Status: accepted · Date: 2026-10-31 · Service: `backend/services/employee_qa`

## Context

The assistant must answer only from company documents, on a small local model (Ollama, e.g. a 4B model with an
8k context window), without embeddings, vector databases or heavy dependencies. Each audience currently has about
5,000 (employee) to 6,000 (HR) tokens of policy text.

## Decision

Two strategies behind one interface (`ContextStrategy.select(question) -> Selection`), chosen automatically:

- **Full context** when all accessible sections fit `FULL_CONTEXT_TOKEN_BUDGET` (default 3000 tokens for local models).
  The model sees everything and decides; nothing relevant can be missed by retrieval.
- **BM25 retrieval** otherwise: pure Python, top 5 sections, light stemming, a small synonym map and typo tolerance.
  A minimum score (`BM25_MIN_SCORE`) lets the assistant abstain **without calling the LLM** when nothing is relevant.

The access filter runs before either strategy, so HR-only text can never be selected for an employee.

## Calibration

On `data/hr_documents/eval/questions.jsonl`, the section each answer needs scores at least 5.31, and clearly
unrelated questions (stock options, company car, weather) score at most 3.94. `BM25_MIN_SCORE = 4.5` keeps a margin
below every needed section and skips the LLM for those questions. Two unanswerable questions share real words with the
corpus (relocation "from abroad" 5.17; an employee asking about HR-only salary ranges 5.66), so no threshold can
separate them; they reach the model, whose abstention plus code validation handles them. A tighter threshold (5.24)
would fit this small set but would overfit.

## Consequences

- With today's corpus, `auto` uses retrieval for employees (~300 prompt tokens instead of ~5,600): faster on a local
  model and well inside the context window. Full context stays available (`--mode full`) for comparison.
- Recall depends on vocabulary overlap; the synonym map and the eval set must grow with the corpus.
- If the corpus grows past a few hundred sections or recall drops, revisit with embeddings (would add a dependency).
