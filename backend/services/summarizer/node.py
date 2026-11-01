# Orchestrator node entrypoint for the summarizer service

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from .classify import ClassifierDeps, classify_email
from .flag_human import code_only_result
from .models import EmailType, InboundEmail


def load_default_deps() -> ClassifierDeps:
    """Wire the shared LLM client, candidate directory, and injection detector."""
    from core.db.repositories import get_candidate_directory
    from core.llm.client import LLMError, get_llm_client
    from security.injection_detector import is_suspicious
    from security.phishing_detector import assess_phishing

    try:
        llm = get_llm_client()
    except LLMError:
        llm = None
    return ClassifierDeps(
        llm=llm, candidates=get_candidate_directory(), detector=is_suspicious, phishing_detector=assess_phishing
    )


def classify_node(state: Mapping[str, Any], deps: ClassifierDeps | None = None) -> dict[str, Any]:
    """Label the email in `state["email"]`. Safe to re-run, because it has no external side effects."""
    deps = deps if deps is not None else load_default_deps()
    email = state.get("email")
    email = email if isinstance(email, Mapping) else {}
    try:
        result = classify_email(InboundEmail.model_validate(email), deps)
    except ValidationError:
        result = code_only_result(
            str(email.get("email_id", "unknown")), EmailType.UNCLASSIFIED, "unknown", "invalid_email"
        )
    return {"classification": result.model_dump(mode="json")}
