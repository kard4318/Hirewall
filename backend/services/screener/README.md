# Screener Service

Screens and ranks candidate resumes against job offers. It ranks, flags and
explains; it never shortlists or rejects anyone. Only a recruiter does that,
through the approval queue.

## Status

| Part | File | Status |
|---|---|---|
| Public facade | `service.py` | Done, tested |
| Data models | `models.py` | Done |
| Config | `config.py` | Done |
| Storage | `storage.py` | Done, tested |
| Validation, visible text, identity split | `security/file_validator.py`, `text_extractor.py`, `pii_bias_filter.py` | Done, tested |
| Injection excerpts (EN/FR/AR) | `security/injection_detector.py` | Done, tested |
| Profile extraction | `extract.py`, `prompts/extract_system_v1.md` | Done, tested |
| Semantic score | `scoring/semantic.py`, `scoring/chunking.py` | Done, tested |
| Embeddings (shared) | `core/llm/embeddings.py` | Done, tested |
| Experience score | `scoring/experience.py` | Done, tested |
| Skill taxonomy | `graph_store/taxonomy.py` | Done, tested |
| LLM rubric | `justify.py`, `prompts/rubric_system_v1.md` | Done, tested |
| Combined ranking | `scoring/ranking_engine.py` | Done, tested |
| Orchestrator node | `node.py`, `orchestrator/record_approval.py` | Done, tested |
| HTTP routes | `gateway/routers/screener.py`, `approvals.py`, `audit.py` | Done, tested |
| Talent Orbit UI | `frontend/src/features/screening/` | Done, built; no automated UI tests |
| Attack suite | `data/attacks/resumes/`, `tests/test_screener_attacks.py` | Done, tested |
| Offer import and publishing | `job_extract.py`, `prompts/job_extract_system_v1.md` | Done, tested |
| Applications and cover letters | `service.py`, `cover_letter.py`, `prompts/cover_letter_system_v1.md` | Done, tested |
| Public offers and applying | `gateway/routers/jobs.py`, `frontend/src/features/apply/` | Done, tested; no automated UI tests |
| Offer and letter attacks | `data/attacks/applications/`, `tests/test_screener_applications.py` | Done, tested |
| Graph score (Neo4j) | `graph_store/neo4j_writer.py` | Next; `NullGraphScorer` holds the slot |
| Scheduler handoff | `services/scheduler` port `ScreenerResults` | Next; the scheduler still reads the mock |
| Rasch scoring | `scoring/rasch_scoring.py` | Not planned (see below) |

The contract is in `docs/api-contract.md` and the threat model in `docs/security.md`. To run it, see "Run the screener" in the root README.

## Offers and applications

HR imports an offer document, reviews the extracted fields, and publishes it. Publishing gives a normal `JobOffer`, with
requirements derived in code. Applicants apply on the public `/jobs` pages. A job with applications scores only its
applicants; a job without any scores the whole pool, as before.

**A cover letter is display only.** It never feeds `rank_combined` or the rubric, so it cannot change a score. Its
injection flags are shown to HR on that application only.

## Inputs / Outputs

**Input:** `CandidateDocument` (from `security/` after sanitization):
pseudonymous `candidate_id`, visible text sections only (no name, contact
details, photo, age, address or hidden text), and `injection_flag`.
Plus a `JobOffer` with typed requirements (`required`, `preferred`,
`responsibility`).

**Output:** `SemanticRanking`: model id, config used (store it for audit),
and per candidate a score in 0..1, requirements met, the injection flag, and
for every requirement the best-matching evidence chunk.

## How it works

1. `SemanticIndex.upsert()` splits each resume into sentence/bullet chunks,
   deduplicates them, caps them at 60, and embeds them once.
2. `SemanticIndex.rank()` embeds each requirement as a query. For every
   candidate, each requirement takes its best-matching chunk.
3. Similarities are calibrated to 0..1 between `floor` and `ceiling`, then
   averaged with weights (required 2, preferred 1, responsibility 1).

Default model: `intfloat/multilingual-e5-small`, run locally, so candidate
text never leaves the machine. Resumes can be in English, French or Arabic.

## How to test alone

```bash
cd backend
pip install -r requirements.txt
pytest services/screener -q                                       # offline
cd .. && python scripts/demo_screener_semantic.py --job job-backend-python
python scripts/demo_screener_semantic.py --job job-data-analyst --fake   # offline
```

## Calibrate before trusting scores

The default `floor=0.78, ceiling=0.90` is a starting guess for E5. Run the
demo with the real model and read `raw_similarity` in the evidence. Set
`floor` just above typical unrelated pairs and `ceiling` near typical good
matches. Override with `SCREENER_SEMANTIC_FLOOR` / `SCREENER_SEMANTIC_CEILING`.

## Security and fairness notes

- Input must be sanitized visible text. Hidden keyword stuffing inflates
  semantic scores, so hidden text must be removed upstream.
- Repeating a line adds nothing, but a visible skills list with no supporting
  experience can still score well (`cand-008` in the sample data). The graph
  score and human review exist for that.
- `injection_flag` is carried through, never used to filter.
- Evidence text is for the recruiter UI. Never pass it to an LLM without
  fencing it as untrusted data.

## Why no Rasch scoring

`rasch_scoring.py` comes from HireMatch AI, where it needs a large real
dataset to estimate skill difficulty. With synthetic data the estimates are
meaningless and hard to explain. The graph score covers skill coverage with
related-skill credit instead.

## Owner

TBD
