# The screener's public facade: ingest resumes, score candidates, prepare decisions for human approval
"""ScreeningService is the only entry point to this service. See docs/api-contract.md.

It ranks, flags and explains. It never records a decision: a proposal goes through
the orchestrator and the approval queue, and only core/executor records it.
"""
import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any

from core.approval_queue.approval_queue import action_hash
from core.audit.audit_log import AuditLog, get_audit_sink
from core.candidate_status.store import CandidateStatusStore, get_candidate_status_store
from core.llm.client import LLMClient, get_llm_client
from core.llm.embeddings import Embedder, HashingEmbedder, SentenceTransformerEmbedder
from core.paths import data_dir
from security.file_validator import FileRejected, validate_upload
from security.injection_detector import find_injection_lines, remove_injection_lines
from security.pii_bias_filter import mask_identity, split_identity
from security.text_extractor import extract_visible_text
from services.screener.config import (
    RUBRIC_PROMPT_VERSION,
    RankingWeights,
    SemanticConfig,
    as_of_date,
    embedder_name,
    embedding_model,
)
from services.screener.extract import Extraction, clean_profile, extract_document, split_sections
from services.screener.graph_store.taxonomy import default_taxonomy
from services.screener.justify import score_rubric
from services.screener.models import (
    CandidateDocument,
    CandidateProfile,
    CandidateSummary,
    CertificationEntry,
    EducationEntry,
    EvidenceChunk,
    FileResult,
    IdentityRecord,
    IngestionTask,
    JobOffer,
    Position,
    ProposedRecordAction,
    RankedCandidate,
    RecordPayload,
    Requirement,
    RubricResult,
    ScreeningRun,
    SemanticRanking,
    StoredCandidate,
)
from services.screener.scoring.experience import parse_required_years
from services.screener.scoring.ranking_engine import job_text, profile_family, rank_combined
from services.screener.scoring.semantic import SemanticIndex
from services.screener.storage import IdentityStore, ScreenerStore

logger = logging.getLogger(__name__)

MAX_FILES = 20
_MIN_TEXT_CHARS = 30
_ACTIONS = {"shortlist": "record_shortlist", "rejection": "record_rejection"}
_UNSET: Any = object()


class ScreenerError(Exception):
    """A request that cannot be served. The message is a short code, safe to show and log."""


class _FixedRanking:
    """One semantic ranking reused for every progress update, so requirements are embedded once per run."""

    def __init__(self, ranking: SemanticRanking) -> None:
        self._ranking = ranking

    def rank(self, job: JobOffer, top_k: int | None = None) -> SemanticRanking:
        return self._ranking


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ScreeningService:
    def __init__(
        self,
        *,
        store: ScreenerStore | None = None,
        identity: IdentityStore | None = None,
        audit: AuditLog | None = None,
        status_store: CandidateStatusStore | None = None,
        llm: LLMClient | Any = _UNSET,
        embedder: Embedder | None = None,
        semantic_config: SemanticConfig | None = None,
        weights: RankingWeights | None = None,
        background: bool = True,
    ) -> None:
        self._store = store or ScreenerStore()
        self._identity = identity or IdentityStore()
        self._audit = audit or get_audit_sink()
        self._status_store = status_store or get_candidate_status_store()
        self._llm_client = llm
        self._embedder_instance = embedder
        self._semantic_config = semantic_config
        self._weights = weights or RankingWeights()
        self._taxonomy = default_taxonomy()
        # One worker: a local model handles one request at a time anyway.
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="screener") if background else None

    def _llm(self) -> Any:
        if self._llm_client is _UNSET:
            try:
                self._llm_client = get_llm_client()
            except Exception as error:
                logger.warning("llm unavailable error_type=%s", type(error).__name__)
                self._llm_client = None
        return self._llm_client

    def _llm_id(self) -> str:
        llm = self._llm()
        return str(getattr(llm, "model", None) or getattr(llm, "_model", None) or type(llm).__name__)

    def _embedder(self) -> Embedder:
        if self._embedder_instance is None:
            if embedder_name() == "hashing":
                self._embedder_instance = HashingEmbedder()
                self._semantic_config = self._semantic_config or SemanticConfig(floor=0.0, ceiling=0.6)
            else:
                self._embedder_instance = SentenceTransformerEmbedder(embedding_model())
        return self._embedder_instance

    # Ingestion

    def ingest_files(self, files: list[tuple[str, bytes]]) -> IngestionTask:
        steps = [lambda i=i, name=name, data=data: self._ingest_file(i, name, data)
                 for i, (name, data) in enumerate(files[:MAX_FILES])]
        return self._start_task(steps)

    def load_demo(self) -> IngestionTask:
        folder = data_dir() / "resumes"
        entries = json.loads((folder / "demo_candidates.json").read_text(encoding="utf-8"))
        pdfs = sorted((folder / "cvs").glob("*.pdf"))
        steps: list[Callable[[], FileResult]] = [
            lambda i=i, entry=entry: self._ingest_demo_entry(i, entry) for i, entry in enumerate(entries)
        ]
        steps += [
            lambda i=len(entries) + i, path=path: self._ingest_file(i, path.name, path.read_bytes(), source="demo")
            for i, path in enumerate(pdfs)
        ]
        return self._start_task(steps)

    def get_task(self, task_id: str) -> IngestionTask:
        task = self._store.get_task(task_id)
        if task is None:
            raise ScreenerError("task_not_found")
        return task

    def _start_task(self, steps: list[Callable[[], FileResult]]) -> IngestionTask:
        task = IngestionTask(task_id=f"task-{uuid.uuid4().hex[:12]}", total=len(steps))
        self._store.save_task(task)
        if self._pool is None:
            self._run_task(task, steps)
        else:
            self._pool.submit(self._run_task, task, steps)
        return task

    def _run_task(self, task: IngestionTask, steps: list[Callable[[], FileResult]]) -> None:
        task.status = "running"
        self._store.save_task(task)
        for index, step in enumerate(steps):
            try:
                result = step()
            except Exception as error:
                # A file must never stop the batch. The error type is safe to log; its message may quote the file.
                logger.error("ingest failed index=%s error_type=%s", index, type(error).__name__)
                result = FileResult(index=index, status="failed", reason_code="ingest_failed")
            task.files.append(result)
            task.done = index + 1
            self._store.save_task(task)
        task.status = "done"
        self._store.save_task(task)

    def _ingest_file(self, index: int, filename: str, data: bytes, *, source: str = "upload") -> FileResult:
        content_hash = hashlib.sha256(data).hexdigest()
        existing = self._store.candidate_by_hash(content_hash)
        if existing:
            return self._duplicate(index, existing)
        try:
            extracted = extract_visible_text(validate_upload(filename, data))
        except FileRejected as rejected:
            return FileResult(index=index, status="rejected", reason_code=str(rejected))
        return self._accept(
            index, extracted.text, content_hash, source,
            hidden_lines=list(extracted.hidden_lines), hidden_removed=extracted.hidden_removed,
        )

    def _ingest_demo_entry(self, index: int, entry: dict[str, Any]) -> FileResult:
        content_hash = _sha256(_canonical(entry))
        existing = self._store.candidate_by_hash(content_hash)
        if existing:
            return self._duplicate(index, existing)
        name = " ".join(filter(None, (entry["name"].get("first_name"), entry["name"].get("last_name"))))
        return self._accept(
            index, _demo_text(entry), content_hash, "demo", known_name=name or None, profile=_demo_profile(entry)
        )

    @staticmethod
    def _duplicate(index: int, existing: StoredCandidate) -> FileResult:
        return FileResult(
            index=index, status="duplicate", candidate_id=existing.candidate_id,
            injection_flag=existing.document.injection_flag, hidden_text_removed=existing.hidden_text_removed,
            extraction_failed=existing.extraction_failed,
        )

    def _accept(
        self,
        index: int,
        visible: str,
        content_hash: str,
        source: str,
        *,
        hidden_lines: list[str] | None = None,
        hidden_removed: bool = False,
        known_name: str | None = None,
        profile: CandidateProfile | None = None,
    ) -> FileResult:
        # Injection comes first: a line turned into "[CANDIDATE] ..." by the identity step could dodge the patterns.
        excerpts = find_injection_lines(visible)
        excerpts += [f"[hidden] {line}" for line in find_injection_lines("\n".join(hidden_lines or []))]
        identity, evidence = split_identity(remove_injection_lines(visible), known_name)
        if len(evidence) < _MIN_TEXT_CHARS:
            return FileResult(index=index, status="rejected", reason_code="no_text", injection_flag=bool(excerpts))

        candidate_id = f"cand-{content_hash[:12]}"
        if profile is not None:
            extraction = Extraction(split_sections(evidence), clean_profile(profile), False)
        else:
            extraction = extract_document(evidence, self._llm())
        document = CandidateDocument(
            candidate_id=candidate_id, sections=extraction.sections, injection_flag=bool(excerpts)
        )
        skills = self._taxonomy.find_skills("\n".join(s.text for s in document.sections))
        stored = StoredCandidate(
            candidate_id=candidate_id,
            content_hash=content_hash,
            source=source,
            document=document,
            profile=extraction.profile,
            extraction_failed=extraction.extraction_failed,
            injection_excerpts=[mask_identity(excerpt, identity) for excerpt in excerpts],
            hidden_text_removed=hidden_removed,
            family=profile_family(skills, self._taxonomy),
        )
        self._identity.save(IdentityRecord(candidate_id=candidate_id, **_identity_fields(identity)))
        self._store.add_candidate(stored)
        self._audit.record(
            "screener.candidate_ingested", candidate_id=candidate_id, source=source,
            injection_flag=document.injection_flag, hidden_text_removed=hidden_removed,
            extraction_failed=extraction.extraction_failed,
        )
        return FileResult(
            index=index, status="accepted", candidate_id=candidate_id, injection_flag=document.injection_flag,
            hidden_text_removed=hidden_removed, extraction_failed=extraction.extraction_failed,
        )

    def list_candidates(self) -> list[CandidateSummary]:
        return [
            CandidateSummary(
                candidate_id=c.candidate_id,
                source=c.source,
                profile=c.family,
                current_title=c.profile.current_title if c.profile else None,
                skills=sorted(self._taxonomy.find_skills("\n".join(s.text for s in c.document.sections))),
                injection_flag=c.document.injection_flag,
                hidden_text_removed=c.hidden_text_removed,
                extraction_failed=c.extraction_failed,
            )
            for c in self._store.list_candidates()
        ]

    # Jobs

    def list_jobs(self) -> list[JobOffer]:
        jobs: dict[str, JobOffer] = {}
        for path in sorted((data_dir() / "job_offers").glob("*.json")):
            for raw in json.loads(path.read_text(encoding="utf-8")):
                job = JobOffer.model_validate(raw)
                jobs[job.job_id] = job
        for job in self._store.list_jobs():
            jobs[job.job_id] = job
        return list(jobs.values())

    def get_job(self, job_id: str) -> JobOffer:
        for job in self.list_jobs():
            if job.job_id == job_id:
                return job
        raise ScreenerError("job_not_found")

    def create_job(self, title: str, requirements: list[Requirement]) -> JobOffer:
        job = JobOffer(job_id=f"job-{uuid.uuid4().hex[:8]}", title=title, requirements=requirements)
        self._store.save_job(job)
        return job

    # Scoring

    def start_run(self, job_id: str) -> ScreeningRun:
        job = self.get_job(job_id)
        ids = [candidate.candidate_id for candidate in self._store.list_candidates()]
        if not ids:
            raise ScreenerError("no_candidates")
        run = ScreeningRun(
            run_id=f"run-{uuid.uuid4().hex[:12]}",
            job_id=job.job_id,
            total=len(ids),
            pending=ids,
            as_of=as_of_date(),
            weights_config=self._weights.as_dict(),
            required_years=parse_required_years(job_text(job)),
            rubric_prompt_version=RUBRIC_PROMPT_VERSION,
        )
        self._store.save_run(run)
        return run

    def execute_run(self, run_id: str) -> ScreeningRun:
        """Score one run, saving progress after each candidate. A finished run is returned as it is."""
        run = self._require_run(run_id)
        if run.status == "done":
            return run
        try:
            self._score(run)
        except Exception as error:
            logger.error("run failed run_id=%s error_type=%s", run_id, type(error).__name__)
            run.status, run.reason_code = "failed", "scoring_failed"
            self._store.save_run(run)
        self._audit.record(
            "screener.run_finished", run_id=run_id, job_id=run.job_id, status=run.status, scored=run.done,
            reason_code=run.reason_code,
        )
        return run

    def _score(self, run: ScreeningRun) -> None:
        job = self.get_job(run.job_id)
        run.status, run.reason_code = "running", None
        run.llm_model = self._llm_id()
        self._store.save_run(run)

        results: dict[str, RubricResult] = {c.candidate_id: c.rubric for c in run.candidates}
        stored = {
            cid: candidate
            for cid in (*results, *run.pending)
            if (candidate := self._store.get_candidate(cid)) is not None
        }
        index = SemanticIndex(self._embedder(), self._semantic_config)
        index.upsert(candidate.document for candidate in stored.values())
        semantic = index.rank(job)
        run.semantic_model_id = semantic.model_id

        for candidate_id in list(run.pending):
            candidate = stored.get(candidate_id)
            if candidate is not None:
                results[candidate_id] = self._rubric(job, candidate)
                ranking = rank_combined(
                    job,
                    [stored[cid].document for cid in results],
                    _FixedRanking(semantic),
                    as_of=run.as_of,
                    weights=self._weights,
                    taxonomy=self._taxonomy,
                    rubric=results,
                )
                run.candidates = [self._with_details(c, stored[c.candidate_id], index) for c in ranking.candidates]
            run.pending.remove(candidate_id)
            run.done += 1
            self._store.save_run(run)
        run.status = "done"
        self._store.save_run(run)

    def _rubric(self, job: JobOffer, candidate: StoredCandidate) -> RubricResult:
        key = _sha256(_canonical([
            candidate.document.model_dump(mode="json"), job.model_dump(mode="json"),
            RUBRIC_PROMPT_VERSION, self._llm_id(),
        ]))
        cached = self._store.cached_rubric(key)
        if cached:
            return RubricResult.model_validate_json(cached)
        result = score_rubric(job, candidate.document, candidate.profile, self._llm())
        if result.score is not None:
            self._store.cache_rubric(key, result.model_dump_json())
        return result

    @staticmethod
    def _with_details(ranked: RankedCandidate, candidate: StoredCandidate, index: SemanticIndex) -> RankedCandidate:
        """Add what the reviewer reads. Everything here is display only and added after the score is computed."""
        chunk_ids = list(dict.fromkeys(e.best_chunk_id for e in ranked.evidence if e.best_chunk_id))
        chunks = [EvidenceChunk(chunk_id=cid, text=index.chunk_text(cid) or "") for cid in chunk_ids]
        return ranked.model_copy(update={
            "evidence_chunks": chunks,
            "injection_excerpts": candidate.injection_excerpts,
            "hidden_text_removed": candidate.hidden_text_removed,
            "profile": candidate.family,
        })

    def _require_run(self, run_id: str) -> ScreeningRun:
        run = self._store.get_run(run_id)
        if run is None:
            raise ScreenerError("run_not_found")
        return run

    def get_run(self, run_id: str) -> ScreeningRun:
        run = self._require_run(run_id)
        run.statuses = self._status_store.statuses_for(run.job_id)
        return run

    # Decisions

    def prepare_proposal(self, run_id: str, candidate_ids: list[str], kind: str) -> str:
        """Save what the recruiter selected. Nothing is recorded until a human approves it."""
        run = self._require_run(run_id)
        if run.status != "done":
            raise ScreenerError("run_not_finished")
        selected = sorted(set(candidate_ids))
        if not selected:
            raise ScreenerError("empty_selection")
        if not set(selected) <= {c.candidate_id for c in run.candidates}:
            raise ScreenerError("unknown_candidate")
        action_type = _ACTIONS[kind]
        payload = RecordPayload(job_id=run.job_id, run_id=run_id, candidate_ids=selected).model_dump()
        proposal_id = _sha256(_canonical({"action_type": action_type, "payload": payload}))[:32]
        self._store.save_proposal(proposal_id, {"action_type": action_type, "payload": payload})
        return proposal_id

    def build_proposed_action(self, proposal_id: str) -> dict[str, Any]:
        proposal = self._store.get_proposal(proposal_id)
        if proposal is None:
            raise ScreenerError("proposal_not_found")
        action_type, payload = proposal["action_type"], proposal["payload"]
        return ProposedRecordAction(
            action_type=action_type,
            payload=RecordPayload(**payload),
            in_reply_to=f"{action_type}:{payload['job_id']}",
            payload_hash=action_hash(action_type, payload),
            idempotency_key=proposal_id,
        ).model_dump(mode="json")

    def reveal_identity(self, candidate_id: str, reviewer: str) -> IdentityRecord:
        if self._store.get_candidate(candidate_id) is None:
            raise ScreenerError("candidate_not_found")
        self._audit.record("screener.identity_revealed", candidate_id=candidate_id, reviewer=reviewer)
        return self._identity.get(candidate_id) or IdentityRecord(candidate_id=candidate_id)


def _identity_fields(identity: Any) -> dict[str, Any]:
    return {key: list(value) if isinstance(value, tuple) else value for key, value in asdict(identity).items()}


def _demo_text(entry: dict[str, Any]) -> str:
    """A demo profile as resume text, so it takes the same path through the checks as an upload."""
    lines = [entry.get("job_title", ""), "EXPERIENCE"]
    for job in entry.get("experience", []):
        lines += [f"{job.get('title', '')}, {job.get('company', '')} ({job.get('year', '')})", ""]
    lines.append("EDUCATION")
    lines += [f"{e.get('degree', '')}, {e.get('university', '')} ({e.get('year', '')})" for e in entry.get("education", [])]
    lines.append("SKILLS")
    lines += list(entry.get("skills", []))
    if entry.get("certifications"):
        lines.append("CERTIFICATIONS")
        lines += [f"{c.get('name', '')}, {c.get('provider', '')} ({c.get('year', '')})" for c in entry["certifications"]]
    if entry.get("other_info"):
        lines += ["OTHER", entry["other_info"]]
    return "\n".join(lines)


def _demo_profile(entry: dict[str, Any]) -> CandidateProfile:
    return CandidateProfile(
        current_title=entry.get("job_title"),
        positions=[
            Position(title=job.get("title", ""), organization=job.get("company", ""), end=str(job.get("year", "")))
            for job in entry.get("experience", [])
        ],
        skills=[skill[:100] for skill in entry.get("skills", [])],
        education=[
            EducationEntry(degree=e.get("degree", ""), institution=e.get("university", ""), year=str(e.get("year", "")))
            for e in entry.get("education", [])
        ],
        certifications=[
            CertificationEntry(name=c.get("name", ""), issuer=c.get("provider", ""), year=str(c.get("year", "")))
            for c in entry.get("certifications", [])
        ],
    )
