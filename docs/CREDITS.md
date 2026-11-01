# Credits

Attribution for all third-party code, libraries, datasets and assets used in Hirewall.

TODO

## Drafter

- [Ollama](https://github.com/ollama/ollama) and its [Python client](https://github.com/ollama/ollama-python) (MIT): run the model locally.
- [Qwen3.5](https://ollama.com/library/qwen3.5): the default local model. Check its license on that page before any non-hackathon use.
- [LangGraph](https://github.com/langchain-ai/langgraph) (MIT): the orchestrator's workflow graph, pause and resume, and checkpoints.
- [HTTPX](https://github.com/encode/httpx) (BSD-3-Clause): network error handling and offline test transport.
- [python-dotenv](https://github.com/theskumar/python-dotenv) (BSD-3-Clause): loads the local `.env` file.
- [Pydantic](https://github.com/pydantic/pydantic) (MIT): data validation.
- [pytest](https://github.com/pytest-dev/pytest) (MIT): testing.
- [nestauk/email-agent-framework](https://github.com/nestauk/email-agent-framework) (MIT, Copyright (c) 2025, Nesta): design inspiration only. The rule to confirm documents and approvals before promising them, and the idea of escalating to a human instead of guessing, were reworded in `backend/services/drafter/prompts/drafter_system_v1.md`. No code was copied.
