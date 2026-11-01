# Orchestrator node entrypoint for the drafter service

import hashlib
import importlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from core.approval_queue.approval_queue import payload_hash
from security.sanitizer import clean_single_line, new_boundary, normalize_address, normalize_newlines

from .checks import (
    base_language,
    build_evidence,
    check_draft,
    check_format,
    check_text,
)
from .config import DEFAULT_CONFIG, DrafterConfig
from .context_builder import BuiltContext, CandidateDirectory, build_context, resolve_candidate
from .models import Claim, DraftContext, DraftRequest, DraftResult, Intent, ProposedAction, ReasonCode
from .writer import DraftGenerationError, LLMClient, render_fallback, write_draft

logger = logging.getLogger(__name__)

_HUMAN_MESSAGES = {
    ReasonCode.INVALID_REQUEST: "The request could not be validated. Please handle this email manually.",
    ReasonCode.CANDIDATE_LOOKUP_UNAVAILABLE: "The candidate directory is unavailable. Please reply manually.",
    ReasonCode.UNKNOWN_SENDER: "The sender does not match a candidate. No reply was drafted.",
    ReasonCode.AMBIGUOUS_SENDER: "The sender matches more than one candidate. No reply was drafted.",
    ReasonCode.INVALID_CANDIDATE_RECORD: "The candidate's record is incomplete or invalid. No reply was drafted.",
    ReasonCode.INJECTION_SUSPECTED: "This email looks like a prompt injection attempt. No reply was drafted.",
    ReasonCode.LLM_UNAVAILABLE: "The drafting model is unavailable. Please reply manually.",
    ReasonCode.LLM_FAILED: "The drafting model failed. Please reply manually.",
    ReasonCode.UNSUPPORTED_LANGUAGE: "The email is in a language the drafter is not configured for.",
    ReasonCode.REVISION_LIMIT_REACHED: "The redraft limit was reached. Please edit the draft or reply manually.",
    ReasonCode.INTERNAL_ERROR: "An unexpected error occurred. Please handle this email manually.",
}
_BLOCKED_MESSAGE = "The draft failed safety checks and was withheld: {codes}. Please reply manually."


class AuditSink(Protocol):
    def record(self, event: str, **fields: Any) -> None: ...


@dataclass(frozen=True)
class DrafterDeps:
    llm: LLMClient | None = None
    candidates: CandidateDirectory | None = None
    detector: Callable[[str], bool] | None = None
    audit: AuditSink | None = None
    config: DrafterConfig = DEFAULT_CONFIG
    boundary_factory: Callable[[], str] = new_boundary


def _optional_factory(module_name: str, attribute: str) -> Any:
    try:
        return getattr(importlib.import_module(module_name), attribute, None)
    except ImportError:
        return None


def _optional_instance(module_name: str, attribute: str) -> Any:
    factory = _optional_factory(module_name, attribute)
    if factory is None:
        return None
    try:
        return factory()
    except Exception as error:
        logger.warning("drafter dependency failed name=%s error_type=%s", attribute, type(error).__name__)
        return None


def load_default_deps() -> DrafterDeps:
    """Wire shared modules that exist. Anything missing fails safe at run time."""
    return DrafterDeps(
        llm=_optional_instance("core.llm.client", "get_llm_client"),
        candidates=_optional_instance("core.db.repositories", "get_candidate_directory"),
        detector=_optional_factory("security.injection_detector", "is_suspicious"),
        audit=_optional_instance("core.audit.audit_log", "get_audit_sink"),
    )


def _result(status: str, reason: ReasonCode, message: str | None = None) -> DraftResult:
    return DraftResult(status=status, reason_code=reason, human_message=message or _HUMAN_MESSAGES.get(reason))


def _needs_human(reason: ReasonCode, message: str | None = None) -> DraftResult:
    return _result("needs_human", reason, message)


def _blocked(codes: list[ReasonCode]) -> DraftResult:
    listed = ", ".join(code.value for code in codes)
    return _needs_human(codes[0], _BLOCKED_MESSAGE.format(codes=listed))


def _sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _proposal(
    *,
    request: DraftRequest,
    context: DraftContext,
    to: str,
    subject: str,
    body: str,
    intent: Intent,
    claims: list[Claim],
    warnings: list[str],
    revision: int,
    config: DrafterConfig,
) -> ProposedAction:
    in_reply_to = request.email.email_id
    return ProposedAction(
        candidate_id=context.candidate_id,
        to=to,
        subject=subject,
        body=body,
        in_reply_to=in_reply_to,
        intent=intent,
        claims=claims,
        warnings=list(dict.fromkeys(warnings)),
        payload_hash=payload_hash(to, subject, body, in_reply_to),
        idempotency_key=_sha256({"email_id": in_reply_to, "candidate_id": context.candidate_id, "revision": revision}),
        revision=revision,
        prompt_version=config.prompt_version,
    )


def _detect_injection(request: DraftRequest, built: BuiltContext, deps: DrafterDeps) -> tuple[bool, list[str]]:
    if deps.detector is None:
        return False, ["injection_detector_unavailable"]
    texts = [f"{request.email.subject}\n{request.email.body}"]
    texts += [message.body for message in request.thread_history if message.direction == "inbound"]
    texts += [
        f"{message.subject}\n{message.body}" for message in built.context.thread if message.direction == "inbound"
    ]
    try:
        return any(deps.detector(text) for text in texts), []
    except Exception:
        return False, ["injection_detector_unavailable"]


def _fallback(
    request: DraftRequest, context: DraftContext, to: str, warnings: list[str], revision: int, config: DrafterConfig
) -> DraftResult:
    subject, body = render_fallback(context)
    evidence = build_evidence(context, recipient=to)
    report = check_text(subject, body, context=context, evidence=evidence, language="en", config=config)
    if report.blocking:
        return _needs_human(ReasonCode.LLM_FAILED)
    proposal = _proposal(
        request=request,
        context=context,
        to=to,
        subject=subject,
        body=body,
        intent="ack",
        claims=[],
        warnings=[*warnings, *report.warnings, "fallback_template_used"],
        revision=revision,
        config=config,
    )
    return DraftResult(
        status="ready_for_review",
        proposal=proposal,
        human_message="The model failed, so this is a template acknowledgement.",
    )


def _generate(request: DraftRequest, deps: DrafterDeps, feedback: str | None, revision: int) -> DraftResult:
    config = deps.config
    resolution = resolve_candidate(request.email.from_address, deps.candidates)
    if resolution.reason is not None:
        return _needs_human(resolution.reason)
    to = resolution.email

    try:
        built = build_context(request, resolution.record, to, config)
    except (ValidationError, KeyError, TypeError, AttributeError):
        return _needs_human(ReasonCode.INVALID_CANDIDATE_RECORD)

    suspicious, warnings = _detect_injection(request, built, deps)
    if suspicious:
        return _result("quarantined", ReasonCode.INJECTION_SUSPECTED)
    warnings = [*built.warnings, *warnings]

    if deps.llm is None:
        return _needs_human(ReasonCode.LLM_UNAVAILABLE)

    context = built.context
    try:
        draft = write_draft(context, deps.llm, config, feedback=feedback, boundary_factory=deps.boundary_factory)
    except DraftGenerationError:
        # A template would ignore the recruiter's feedback, so redrafts go back to the human.
        if feedback is not None:
            return _needs_human(ReasonCode.LLM_FAILED)
        return _fallback(request, context, to, warnings, revision, config)

    if draft.intent == "escalate" or draft.needs_human_input:
        note = clean_single_line(draft.needs_human_input or "", config.max_human_message_chars).text
        return _needs_human(ReasonCode.LLM_ESCALATED, note or "The model asked for a recruiter to handle this email.")

    language = base_language(draft.language)
    if language not in config.supported_languages:
        return _needs_human(ReasonCode.UNSUPPORTED_LANGUAGE)

    subject, body = draft.subject, normalize_newlines(draft.body)
    evidence = build_evidence(context, recipient=to, feedback=feedback)
    report = check_draft(
        subject,
        body,
        claims=draft.claims,
        intent=draft.intent,
        context=context,
        evidence=evidence,
        language=language,
        config=config,
    )
    if report.blocking:
        return _blocked(report.blocking)

    flags = [f"llm:{clean_single_line(flag, 200).text}" for flag in draft.risk_flags if flag.strip()]
    proposal = _proposal(
        request=request,
        context=context,
        to=to,
        subject=subject,
        body=body,
        intent=draft.intent,
        claims=draft.claims,
        warnings=[*warnings, *report.warnings, *flags],
        revision=revision,
        config=config,
    )
    return DraftResult(status="ready_for_review", proposal=proposal)


def _report_outcome(request: DraftRequest | None, result: DraftResult, deps: DrafterDeps, started: float) -> None:
    fields = {
        "email_id": request.email.email_id if request else None,
        "status": result.status,
        "reason_code": result.reason_code.value if result.reason_code else None,
        "payload_hash": result.proposal.payload_hash if result.proposal else None,
        "prompt_version": deps.config.prompt_version,
        "latency_ms": round((time.monotonic() - started) * 1000),
    }
    logger.info("drafter outcome %s", " ".join(f"{key}={value}" for key, value in fields.items()))
    if deps.audit is not None:
        try:
            deps.audit.record("drafter.outcome", **fields)
        except Exception as error:
            logger.warning("drafter audit failed error_type=%s", type(error).__name__)


def _run(request: DraftRequest, deps: DrafterDeps, feedback: str | None, revision: int) -> DraftResult:
    started = time.monotonic()
    try:
        result = _generate(request, deps, feedback, revision)
    except Exception as error:
        logger.error("drafter failed error_type=%s", type(error).__name__)
        result = _needs_human(ReasonCode.INTERNAL_ERROR)
    _report_outcome(request, result, deps, started)
    return result


def draft_node(state: Mapping[str, Any], deps: DrafterDeps | None = None) -> dict[str, Any]:
    """Produce a draft for review. Safe to re-run, because it has no external side effects."""
    deps = deps if deps is not None else load_default_deps()
    try:
        request = DraftRequest.model_validate(state["draft_request"])
    except (ValidationError, KeyError, TypeError):
        result = _needs_human(ReasonCode.INVALID_REQUEST)
        _report_outcome(None, result, deps, time.monotonic())
        return {"draft_result": result.model_dump(mode="json")}
    return {"draft_result": _run(request, deps, None, 0).model_dump(mode="json")}


def redraft(request: DraftRequest, feedback: str, revision: int, deps: DrafterDeps | None = None) -> DraftResult:
    """Redraft using recruiter feedback. The feedback applies only to this call."""
    deps = deps if deps is not None else load_default_deps()
    if revision > deps.config.max_revisions:
        return _needs_human(ReasonCode.REVISION_LIMIT_REACHED)
    return _run(request, deps, feedback, revision)


def build_review_context(request: DraftRequest, deps: DrafterDeps) -> DraftContext | None:
    """Rebuild the trusted context a recruiter's edit is checked against."""
    resolution = resolve_candidate(request.email.from_address, deps.candidates)
    if resolution.reason is not None:
        return None
    try:
        return build_context(request, resolution.record, resolution.email, deps.config).context
    except (ValidationError, KeyError, TypeError, AttributeError):
        return None


def recheck_edited_draft(
    proposal: ProposedAction,
    edited_subject: str,
    edited_body: str,
    context: DraftContext,
    config: DrafterConfig = DEFAULT_CONFIG,
) -> DraftResult:
    """Re-check a recruiter's edit. Content problems warn, because the human decides."""
    body = normalize_newlines(edited_body)
    blocking = check_format(edited_subject, body, config)
    if blocking:
        return _blocked(blocking)

    to = normalize_address(proposal.to) or proposal.to
    evidence = build_evidence(context, recipient=to)
    language = config.supported_languages[0]
    report = check_text(edited_subject, body, context=context, evidence=evidence, language=language, config=config)
    warnings = ["human_edited", "claims_not_reverified", *report.warnings]
    warnings += [f"edit_warning:{code.value}" for code in report.blocking]
    edited = proposal.model_copy(
        update={
            "subject": edited_subject,
            "body": body,
            "warnings": list(dict.fromkeys(warnings)),
            "payload_hash": payload_hash(to, edited_subject, body, proposal.in_reply_to),
        }
    )
    return DraftResult(status="ready_for_review", proposal=edited)
