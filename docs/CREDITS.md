# Credits

Attribution for all third-party code, libraries, datasets and assets used in Hirewall.

## Code adapted

[NLP-Powered Resume Job Matching & Candidate Ranking System](https://github.com/arpitpandey454507/NLP-Powered-Resume-Job-Matching-Candidate-Ranking-System)
(MIT License, Copyright (c) 2024 AI Resume Screener), commit `538d812`, reached through the `screener` branch of
[AmineMK1337/Hiring-RH](https://github.com/AmineMK1337/Hiring-RH). Adapted files carry the MIT notice in their header.

| Our code | Adapted from (`src/scoring.py` unless noted) | What changed |
|---|---|---|
| `services/screener/scoring/experience.py`: `parse_required_years` | `_extract_required_experience` | French and Arabic patterns, Arabic number words and Eastern Arabic digits, experience context required for bare values |
| `experience.py`: `extract_intervals` | `_extract_experience_intervals` | French, Middle-East and Tunisian Arabic month names, numeric dates, open ranges ("depuis"), fixed `as_of` date instead of `datetime.now()`, future dates cut or dropped |
| `experience.py`: `merge_intervals`, `total_months` | `_merge_intervals`, `_interval_months` | Minor: same logic |
| `experience.py`: `relevant_experience`, `experience_score` | `_estimate_relevant_experience`, `_experience_match` | Relevance per position instead of per section, no role-based fallback, linear score with no 0.8/0.6 steps and no bonus beyond the requirement |
| `services/screener/graph_store/skill_taxonomy.json` | `src/utils/keyword_mapping.py`: `SKILL_GROUPS`, `SKILL_CATEGORIES` | Filtered to software/data/DevOps/frontend skills, short and ambiguous aliases removed, French spellings and a few local skills added, categories remapped |

Ideas taken from the same repo without copying code: N/A criteria excluded with weights renormalized
(`scoring/ranking_engine.py`), and matched / missing / additional skill lists.

`services/screener/scoring/{ranking_engine,normalize}.py` and `graph_store/taxonomy.py` come from the same
`screener` branch of Hiring-RH, our own earlier work. `frontend/src/features/screening/talent-orbit.js` is our own
component from Hiring-RH, copied unchanged.

## Ideas and design references (no code copied)

| Project | License | What we took |
|---|---|---|
| [SmartHire](https://github.com/coding-chemist/SmartHire) | GPL-3.0 | Idea of LLM structured resume extraction with Pydantic schemas, and of a rubric with per-dimension justifications and a computed score. No code or prompt text copied, so GPL obligations do not apply. |
| [HireMatch AI](https://github.com/AKR-2803/hirematch-ai) | none stated | Idea of a Neo4j skills graph (Candidate, Skill, Job). No code copied. |
| [nestauk/email-agent-framework](https://github.com/nestauk/email-agent-framework) | MIT, Copyright (c) 2025, Nesta | The rule to confirm documents and approvals before promising them, and the idea of escalating to a human instead of guessing, reworded in the drafter's system prompts. No code copied. |

## Libraries and models

| Name | License | Used in |
|---|---|---|
| [sentence-transformers](https://github.com/UKPLab/sentence-transformers) | Apache-2.0 | `core/llm/embeddings.py` |
| [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) | MIT | Default screener embedding model |
| [pydantic](https://github.com/pydantic/pydantic) | MIT | Data models |
| [NumPy](https://github.com/numpy/numpy) | BSD-3-Clause | Scoring |
| [Ollama](https://github.com/ollama/ollama) and its [Python client](https://github.com/ollama/ollama-python) | MIT | Runs the model locally |
| [Qwen3.5](https://ollama.com/library/qwen3.5) | Check its model page before any non-hackathon use | Default local model |
| [LangGraph](https://github.com/langchain-ai/langgraph) | MIT | Orchestrator's workflow graph, pause and resume, and checkpoints |
| [HTTPX](https://github.com/encode/httpx) | BSD-3-Clause | Network error handling and offline test transport |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | BSD-3-Clause | Loads the local `.env` file |
| [pdfplumber](https://github.com/jsvine/pdfplumber) (with pdfminer.six, MIT; pypdfium2, Apache-2.0 and BSD-3-Clause; Pillow, MIT-CMU) | MIT | `security/file_validator.py`, `security/text_extractor.py` |
| [python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 | Resume uploads in the gateway |
| [three.js](https://github.com/mrdoob/three.js) 0.160.0 | MIT | Talent Orbit view |
| [pytest](https://github.com/pytest-dev/pytest) | MIT | Testing |
