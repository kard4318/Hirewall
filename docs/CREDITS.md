# Credits

Attribution for all third-party code, libraries, datasets and assets used in Hirewall.

## Ideas and design references (no code copied)

| Project | License | What we took |
|---|---|---|
| [SmartHire](https://github.com/coding-chemist/SmartHire) | GPL-3.0 | Idea of LLM structured resume extraction with Pydantic schemas and per-dimension justifications. No code copied, so GPL obligations do not apply. |
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
| [pytest](https://github.com/pytest-dev/pytest) | MIT | Testing |
