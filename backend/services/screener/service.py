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
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from core.approval_queue.approval_queue import action_hash
from core.audit.audit_log import AuditLog, get_audit_sink
from core.candidate_status.store import CandidateStatusStore, get_candidate_status_store
from core.llm.client import LLMClient, get_llm_client
from core.llm.embeddings import Embedder, HashingEmbedder, SentenceTransformerEmbedder
from core.paths import data_dir
from security.file_validator import FileRejected, validate_upload
from security.injection_detector import find_injection_lines, remove_injection_lines
from security.pii_bias_filter import Identity, mask_identity, split_identity
from security.sanitizer import clean_untrusted_text
from security.text_extractor import MAX_TEXT_CHARS, extract_visible_text
from services.screener.config import (
    RUBRIC_PROMPT_VERSION,
    RankingWeights,
    SemanticConfig,
    as_of_date,
    embedder_name,
    embedding_model,
)
from services.screener.cover_letter import extract_cover_letter
from services.screener.csv_import import CsvRow, Document, file_key
from services.screener.extract import Extraction, clean_profile, extract_document, split_sections
from services.screener.graph_store.taxonomy import default_taxonomy
from services.screener.job_extract import build_requirements, extract_job, flagged_requirements
from services.screener.justify import score_rubric
from services.screener.models import (
    ApplicantContact,
    Application,
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
    JobPosting,
    JobPostingDetails,
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
MAX_QUEUED_APPLICATIONS = 20
_MIN_TEXT_CHARS = 30
_MAX_COVER_LETTER_CHARS = 8000
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        self._queued_applications = 0
        self._queue_lock = Lock()

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

    def ingest_files(self, files: list[tuple[str, bytes]], job_id: str | None = None) -> IngestionTask:
        """With a job_id, each accepted file also becomes an application to that posting."""
        if job_id is not None:
            self._require_posting(job_id, allow={"published", "closed"})

        def step(index: int, name: str, data: bytes) -> FileResult:
            result = self._ingest_file(index, name, data)
            if job_id is not None and result.candidate_id:
                self._link_application(job_id, result.candidate_id, "hr_upload")
            return result

        steps = [lambda i=i, name=name, data=data: step(i, name, data)
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

    def _ingest_file(
        self, index: int, filename: str, data: bytes, *, source: str = "upload", known_name: str | None = None
    ) -> FileResult:
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
            hidden_lines=list(extracted.hidden_lines), hidden_removed=extracted.hidden_removed, known_name=known_name,
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
            created_at=_now(),
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

    def _summary(self, c: StoredCandidate) -> CandidateSummary:
        return CandidateSummary(
            candidate_id=c.candidate_id,
            source=c.source,
            profile=c.family,
            current_title=c.profile.current_title if c.profile else None,
            skills=sorted(self._taxonomy.find_skills("\n".join(s.text for s in c.document.sections))),
            injection_flag=c.document.injection_flag,
            hidden_text_removed=c.hidden_text_removed,
            extraction_failed=c.extraction_failed,
        )

    def list_candidates(self) -> list[CandidateSummary]:
        return [self._summary(c) for c in self._store.list_candidates()]

    def get_extracted(self, candidate_id: str) -> dict[str, Any]:
        """What was extracted from a CV. Pseudonymous: identity only comes from reveal_identity."""
        candidate = self._store.get_candidate(candidate_id)
        if candidate is None:
            raise ScreenerError("candidate_not_found")
        return {
            "candidate_id": candidate_id,
            "profile": candidate.profile.model_dump(mode="json") if candidate.profile else None,
            "sections": [section.model_dump(mode="json") for section in candidate.document.sections],
            "extraction_failed": candidate.extraction_failed,
            "injection_flag": candidate.document.injection_flag,
            "injection_excerpts": candidate.injection_excerpts,
            "hidden_text_removed": candidate.hidden_text_removed,
        }

    # Job postings

    def _require_posting(self, job_id: str, allow: set[str] | None = None) -> JobPosting:
        posting = self._store.get_posting(job_id)
        if posting is None:
            raise ScreenerError("job_not_found")
        if allow is not None and posting.status not in allow:
            raise ScreenerError(f"posting_{posting.status}")
        return posting

    def extract_posting(self, filename: str, data: bytes) -> tuple[IngestionTask, str]:
        """Turn an offer document into a draft in the background. Nothing is public until HR publishes it."""
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        return self._start_task([lambda: self._extract_posting(job_id, filename, data)]), job_id

    def _extract_posting(self, job_id: str, filename: str, data: bytes) -> FileResult:
        try:
            extracted = extract_visible_text(validate_upload(filename, data))
        except FileRejected as rejected:
            return FileResult(index=0, status="rejected", reason_code=str(rejected))
        excerpts = find_injection_lines(extracted.text)
        excerpts += [f"[hidden] {line}" for line in find_injection_lines("\n".join(extracted.hidden_lines))]
        text = remove_injection_lines(extracted.text)
        if len(text.strip()) < _MIN_TEXT_CHARS:
            return FileResult(index=0, status="rejected", reason_code="no_text", injection_flag=bool(excerpts))

        extraction = extract_job(text, self._llm())
        posting = JobPosting(
            job_id=job_id,
            details=extraction.details,
            requirements=build_requirements(extraction.details),
            extraction_failed=extraction.extraction_failed,
            flagged_requirements=flagged_requirements(extraction.details, text),
            injection_excerpts=excerpts,
            hidden_text_removed=extracted.hidden_removed,
            source_hash=hashlib.sha256(data).hexdigest(),
            created_at=_now(),
        )
        self._store.save_posting(posting)
        self._audit.record(
            "screener.job_extracted", job_id=job_id, extraction_failed=posting.extraction_failed,
            flagged_requirements=len(posting.flagged_requirements), injection_flag=bool(excerpts),
            hidden_text_removed=posting.hidden_text_removed,
        )
        return FileResult(
            index=0, status="accepted", injection_flag=bool(excerpts), hidden_text_removed=posting.hidden_text_removed,
            extraction_failed=posting.extraction_failed,
        )

    def get_posting(self, job_id: str) -> JobPosting:
        return self._require_posting(job_id)

    def list_postings(self) -> list[JobPosting]:
        return self._store.list_postings()

    def update_posting(self, job_id: str, details: JobPostingDetails) -> JobPosting:
        """Save HR's edits to a draft. Requirements are derived again, so they always match the details."""
        posting = self._require_posting(job_id, allow={"draft"})
        updated = posting.model_copy(update={
            "details": details,
            "requirements": build_requirements(details),
            "flagged_requirements": flagged_requirements(details),
        })
        self._store.save_posting(updated)
        return updated

    def publish_posting(self, job_id: str) -> JobPosting:
        posting = self._require_posting(job_id, allow={"draft"})
        if not posting.requirements:
            raise ScreenerError("no_requirements")
        published = posting.model_copy(update={"status": "published", "published_at": _now()})
        self._store.save_posting(published)
        self._audit.record(
            "screener.job_published", job_id=job_id, flagged_requirements=len(published.flagged_requirements)
        )
        return published

    def close_posting(self, job_id: str) -> JobPosting:
        posting = self._require_posting(job_id, allow={"published"})
        closed = posting.model_copy(update={"status": "closed", "closed_at": _now()})
        self._store.save_posting(closed)
        self._audit.record("screener.job_closed", job_id=job_id)
        return closed

    def job_rows(self) -> list[dict[str, Any]]:
        """Every job HR can pick, with its status (None for samples, presets and hand-written jobs)."""
        postings = {posting.job_id: posting for posting in self._store.list_postings()}
        rows = [job.model_dump(mode="json") | {"status": None} for job in self.list_jobs() if job.job_id not in postings]
        rows += [
            {"job_id": p.job_id, "title": p.details.title, "status": p.status,
             "requirements": [requirement.model_dump(mode="json") for requirement in p.requirements]}
            for p in postings.values()
        ]
        return [row | {"application_count": len(self._store.list_applications(row["job_id"]))} for row in rows]

    # Public offers

    def _open_posting(self, job_id: str) -> JobPosting:
        """Drafts do not exist for the public. A closed offer says so."""
        posting = self._store.get_posting(job_id)
        if posting is None or posting.status == "draft":
            raise ScreenerError("job_not_found")
        if posting.status == "closed":
            raise ScreenerError("job_closed")
        return posting

    def public_postings(self) -> list[dict[str, Any]]:
        published = [p for p in self._store.list_postings() if p.status == "published"]
        return [self._public_view(posting) for posting in published]

    def public_posting(self, job_id: str) -> dict[str, Any]:
        return self._public_view(self._open_posting(job_id))

    @staticmethod
    def _public_view(posting: JobPosting) -> dict[str, Any]:
        return {"job_id": posting.job_id, "published_at": posting.published_at,
                "details": posting.details.model_dump(mode="json")}

    # Applications

    def check_application_files(self, cv: tuple[str, bytes], cover_letter: tuple[str, bytes] | None) -> None:
        """Refuse bad files while the applicant is still there to see why. No model is involved."""
        for label, item in (("cv", cv), ("cover_letter", cover_letter)):
            if item is None:
                continue
            try:
                extracted = extract_visible_text(validate_upload(*item))
            except FileRejected as rejected:
                raise ScreenerError(f"{label}_{rejected}") from None
            if len(extracted.text.strip()) < _MIN_TEXT_CHARS:
                raise ScreenerError(f"{label}_no_text")

    def submit_application(
        self, job_id: str, cv: tuple[str, bytes], cover_letter: tuple[str, bytes] | None, full_name: str, email: str
    ) -> str:
        """Queue one application and return a reference that says nothing about whether this CV is already known."""
        self._open_posting(job_id)
        with self._queue_lock:
            if self._queued_applications >= MAX_QUEUED_APPLICATIONS:
                raise ScreenerError("try_later")
            self._queued_applications += 1
        reference_id = f"ref-{uuid.uuid4().hex[:12]}"
        contact = ApplicantContact(
            reference_id=reference_id, job_id=job_id, full_name=full_name, email=email, consent_at=_now()
        )
        if self._pool is None:
            self._run_application(contact, cv, cover_letter)
        else:
            self._pool.submit(self._run_application, contact, cv, cover_letter)
        return reference_id

    def _run_application(
        self, contact: ApplicantContact, cv: tuple[str, bytes], cover_letter: tuple[str, bytes] | None
    ) -> None:
        try:
            self._process_application(contact, cv, cover_letter)
        except Exception as error:
            logger.error("application failed reference=%s error_type=%s", contact.reference_id, type(error).__name__)
            self._audit.record(
                "screener.application_rejected", reference_id=contact.reference_id, job_id=contact.job_id,
                reason_code="application_failed",
            )
        finally:
            with self._queue_lock:
                self._queued_applications -= 1

    def _process_application(
        self, contact: ApplicantContact, cv: tuple[str, bytes], cover_letter: tuple[str, bytes] | None
    ) -> None:
        result = self._ingest_file(0, *cv)
        if result.candidate_id is None:
            self._audit.record(
                "screener.application_rejected", reference_id=contact.reference_id, job_id=contact.job_id,
                reason_code=result.reason_code,
            )
            return
        candidate_id = result.candidate_id
        # A CV anyone can resubmit must never let them replace its identity or its first application's letter.
        self._identity.add_contact(candidate_id, contact)
        existing = self._store.get_application(contact.job_id, candidate_id) is not None
        if not existing:
            application = self._new_application(contact.job_id, candidate_id, "applicant")
            if cover_letter is not None:
                application = self._with_cover_letter(application, cover_letter, contact)
            self._store.add_application(application)
        stored = self._store.get_application(contact.job_id, candidate_id)
        self._audit.record(
            "screener.application_received", reference_id=contact.reference_id,
            application_id=stored.application_id, job_id=contact.job_id, candidate_id=candidate_id, source="applicant",
            repeat=existing, cover_letter=stored.cover_letter is not None or stored.cover_letter_text is not None,
            cover_letter_failed=stored.cover_letter_failed, injection_flag=bool(stored.injection_excerpts),
            hidden_text_removed=stored.hidden_text_removed,
        )

    @staticmethod
    def _new_application(job_id: str, candidate_id: str, source: str) -> Application:
        return Application(
            application_id=f"app-{_sha256(f'{job_id}|{candidate_id}')[:16]}",
            job_id=job_id, candidate_id=candidate_id, submitted_at=_now(), source=source,
        )

    def _link_application(self, job_id: str, candidate_id: str, source: str) -> None:
        application = self._new_application(job_id, candidate_id, source)
        if self._store.add_application(application):
            self._audit.record(
                "screener.application_received", application_id=application.application_id, job_id=job_id,
                candidate_id=candidate_id, source=source, repeat=False,
            )

    def _with_cover_letter(
        self, application: Application, cover_letter: tuple[str, bytes], contact: ApplicantContact
    ) -> Application:
        """The same checks as a CV. A bad letter never loses the CV."""
        try:
            extracted = extract_visible_text(validate_upload(*cover_letter))
        except FileRejected as error:
            logger.warning("cover letter refused error_type=%s", type(error).__name__)
            return application.model_copy(update={"cover_letter_failed": True})
        return self._read_letter(application, extracted.text, extracted.hidden_lines, extracted.hidden_removed, contact)

    def _read_letter(
        self, application: Application, visible: str, hidden_lines: tuple[str, ...], hidden_removed: bool,
        contact: ApplicantContact,
    ) -> Application:
        """Masked with what is known about this person, then read by the model. Display only: never scored."""
        excerpts = find_injection_lines(visible)
        excerpts += [f"[hidden] {line}" for line in find_injection_lines("\n".join(hidden_lines))]
        known = self._identity.get(application.candidate_id)
        name = (known.full_name if known else None) or contact.full_name
        _, evidence = split_identity(remove_injection_lines(visible), name)
        typed = Identity(contact.full_name or None, (contact.email,) if contact.email else ())
        found = Identity(known.full_name, tuple(known.emails), tuple(known.phones), tuple(known.links)) if known else None
        for person in filter(None, (found, typed)):
            evidence = mask_identity(evidence, person)
            excerpts = [mask_identity(excerpt, person) for excerpt in excerpts]
        profile = extract_cover_letter(evidence, self._llm())
        return application.model_copy(update={
            "cover_letter": profile,
            "cover_letter_text": evidence[:_MAX_COVER_LETTER_CHARS],
            "cover_letter_failed": profile is None,
            "injection_excerpts": excerpts,
            "hidden_text_removed": hidden_removed,
        })

    # CSV import

    def ingest_csv(self, rows: list[CsvRow], files: dict[str, bytes], job_id: str | None = None) -> IngestionTask:
        """One step per row, in the background. `files` holds the uploads named in the CSV, by original name."""
        if job_id is not None:
            self._require_posting(job_id, allow={"published", "closed"})
        uploads = {file_key(name): (name, data) for name, data in files.items()}
        steps = [lambda i=i, row=row: self._ingest_row(i, row, uploads, job_id) for i, row in enumerate(rows)]
        return self._start_task(steps)

    def _ingest_row(
        self, index: int, row: CsvRow, uploads: dict[str, tuple[str, bytes]], job_id: str | None
    ) -> FileResult:
        if row.cv is None:
            return FileResult(index=index, status="rejected", reason_code="cv_missing")
        if row.cv.file_name is not None:
            upload = uploads.get(row.cv.file_name)
            if upload is None:
                return FileResult(index=index, status="rejected", reason_code="cv_file_missing")
            result = self._ingest_file(index, *upload, known_name=row.name)
        else:
            result = self._ingest_cv_text(index, row.cv.text or "", row.name)
        if result.candidate_id is None:
            return result

        contact = ApplicantContact(
            reference_id=f"csv-{uuid.uuid4().hex[:12]}", job_id=job_id or "", full_name=row.name or "",
            email=row.email or "", consent_at="",
        )
        if row.email:
            self._identity.add_contact(result.candidate_id, contact)
        if job_id is None:
            return result.model_copy(update={"reason_code": "cover_letter_needs_posting"}) if row.cover_letter else result

        note = None
        if self._store.get_application(job_id, result.candidate_id) is None:
            application = self._new_application(job_id, result.candidate_id, "hr_upload")
            if row.cover_letter is not None:
                application, note = self._csv_letter(application, row.cover_letter, uploads, contact)
            if self._store.add_application(application):
                self._audit.record(
                    "screener.application_received", application_id=application.application_id, job_id=job_id,
                    candidate_id=result.candidate_id, source="hr_upload", repeat=False,
                    cover_letter=application.cover_letter_text is not None,
                    cover_letter_failed=application.cover_letter_failed,
                    injection_flag=bool(application.injection_excerpts),
                    hidden_text_removed=application.hidden_text_removed,
                )
        return result.model_copy(update={"reason_code": note}) if note else result

    def _ingest_cv_text(self, index: int, text: str, name: str | None) -> FileResult:
        cleaned = clean_untrusted_text(text, MAX_TEXT_CHARS)
        content_hash = _sha256(cleaned.text)
        existing = self._store.candidate_by_hash(content_hash)
        if existing:
            return self._duplicate(index, existing)
        return self._accept(index, cleaned.text, content_hash, "upload", hidden_removed=cleaned.hidden_removed, known_name=name)

    def _csv_letter(
        self, application: Application, letter: Document, uploads: dict[str, tuple[str, bytes]], contact: ApplicantContact
    ) -> tuple[Application, str | None]:
        if letter.file_name is None:
            cleaned = clean_untrusted_text(letter.text or "", MAX_TEXT_CHARS)
            return self._read_letter(application, cleaned.text, (), cleaned.hidden_removed, contact), None
        upload = uploads.get(letter.file_name)
        if upload is None:
            return application.model_copy(update={"cover_letter_failed": True}), "cover_letter_file_missing"
        return self._with_cover_letter(application, upload, contact), None

    def list_applications(self, job_id: str) -> list[dict[str, Any]]:
        """Pseudonymous rows for HR, with the letter's flags merged into the candidate's."""
        self._require_posting(job_id)
        rows = []
        for application in self._store.list_applications(job_id):
            candidate = self._store.get_candidate(application.candidate_id)
            if candidate is None:
                continue
            summary = self._summary(candidate).model_dump(mode="json")
            excerpts = [*candidate.injection_excerpts, *_letter_excerpts(application)]
            rows.append(application.model_dump(mode="json") | {
                "candidate": summary | {
                    "injection_flag": bool(excerpts),
                    "hidden_text_removed": candidate.hidden_text_removed or application.hidden_text_removed,
                },
                "injection_excerpts": excerpts,
            })
        return rows

    # Jobs

    def list_jobs(self) -> list[JobOffer]:
        jobs: dict[str, JobOffer] = {}
        for path in sorted((data_dir() / "job_offers").glob("*.json")):
            for raw in json.loads(path.read_text(encoding="utf-8")):
                job = JobOffer.model_validate(raw)
                jobs[job.job_id] = job
        for job in self._store.list_jobs():
            jobs[job.job_id] = job
        for posting in self._store.list_postings():
            if posting.status == "published":
                jobs[posting.job_id] = _posting_offer(posting)
        return list(jobs.values())

    def get_job(self, job_id: str) -> JobOffer:
        """Closed postings still resolve, so their runs stay readable. Drafts cannot be scored."""
        posting = self._store.get_posting(job_id)
        if posting is not None:
            if posting.status == "draft":
                raise ScreenerError("posting_draft")
            return _posting_offer(posting)
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
        # A job with applicants scores them alone. Otherwise the whole pool, as for presets and the demo set.
        ids = sorted(a.candidate_id for a in self._store.list_applications(job.job_id))
        ids = ids or [candidate.candidate_id for candidate in self._store.list_candidates()]
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
                run.candidates = [
                    self._with_details(
                        c, stored[c.candidate_id], index, self._store.get_application(job.job_id, c.candidate_id)
                    )
                    for c in ranking.candidates
                ]
            run.pending.remove(candidate_id)
            run.done += 1
            self._store.save_run(run)
        run.status = "done"
        self._store.save_run(run)

    def _rubric(self, job: JobOffer, candidate: StoredCandidate) -> RubricResult:
        # The candidate ID leads the key so erasure can find every cached answer about this person.
        key = candidate.candidate_id + ":" + _sha256(_canonical([
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
    def _with_details(
        ranked: RankedCandidate, candidate: StoredCandidate, index: SemanticIndex, application: Application | None = None
    ) -> RankedCandidate:
        """Add what the reviewer reads. Everything here is display only and added after the score is computed."""
        chunk_ids = list(dict.fromkeys(e.best_chunk_id for e in ranked.evidence if e.best_chunk_id))
        chunks = [EvidenceChunk(chunk_id=cid, text=index.chunk_text(cid) or "") for cid in chunk_ids]
        excerpts = [*candidate.injection_excerpts, *(_letter_excerpts(application) if application else [])]
        return ranked.model_copy(update={
            "evidence_chunks": chunks,
            "injection_flag": bool(excerpts),
            "injection_excerpts": excerpts,
            "hidden_text_removed": candidate.hidden_text_removed or bool(application and application.hidden_text_removed),
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
            in_reply_to=f"{action_type}:{proposal_id}",  # its own scope: one candidate's proposal must not replace another's
            payload_hash=action_hash(action_type, payload),
            idempotency_key=proposal_id,
        ).model_dump(mode="json")

    def decision_contact(self, run_id: str, candidate_id: str, purpose: str) -> dict[str, Any]:
        """Who to tell about an approved decision. The CV's address comes first; the form's is only a fallback."""
        run = self._require_run(run_id)
        ranked = next((c for c in run.candidates if c.candidate_id == candidate_id), None)
        if ranked is None:
            raise ScreenerError("unknown_candidate")
        self._audit.record("screener.contact_used", candidate_id=candidate_id, run_id=run_id, purpose=purpose)
        record = self._identity.get(candidate_id) or IdentityRecord(candidate_id=candidate_id)
        # A contact with no job came from a CSV uploaded with no offer selected.
        form = next((c for c in self._identity.contacts_for(candidate_id) if c.job_id in (run.job_id, "") and c.email), None)
        posting = self._store.get_posting(run.job_id)
        return {
            "email": record.emails[0] if record.emails else (form.email if form else None),
            "full_name": record.full_name or (form.full_name if form else None),
            "job_title": " ".join(self.get_job(run.job_id).title.split()),
            "company": posting.details.company if posting else None,
            "location": posting.details.location if posting else None,
            "score": round(ranked.total_score * 100),
            "matched_skills": ranked.matched_skills,
        }

    def upload_refusals(self) -> dict[str, int]:
        """How many files were refused, by reason code. Counts only: no names or contents are kept."""
        counts: dict[str, int] = {}
        for task in self._store.list_tasks():
            for file in task.files:
                if file.status in ("rejected", "failed") and file.reason_code:
                    counts[file.reason_code] = counts.get(file.reason_code, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: -item[1]))

    # Erasure and retention

    def known_names(self, candidate_id: str) -> list[str]:
        """Name and addresses on file, so other stores can find entries that mention this person."""
        record = self._identity.get(candidate_id)
        contacts = self._identity.contacts_for(candidate_id)
        values = [record.full_name, *record.emails] if record else []
        values += [value for contact in contacts for value in (contact.full_name, contact.email)]
        return sorted({value for value in values if value})

    def erase_candidate(self, candidate_id: str) -> dict[str, int]:
        """Remove one candidate from every screener store and from recorded decisions. Raises if nothing was found."""
        counts = self._store.erase_candidate(candidate_id)
        counts["identity_records"] = self._identity.erase(candidate_id)
        counts["recorded_decisions"] = self._status_store.erase(candidate_id)
        if not any(counts.values()):
            raise ScreenerError("candidate_not_found")
        return counts

    def retention_due(self, now: datetime, days: int) -> list[dict[str, str]]:
        """Candidates whose process ended more than `days` ago, with why it counts as ended.

        Ended means: every job they were attached to is closed; or every decision recorded for them is a rejection;
        or they were never attached to a job and never decided on (an idle pool entry). Shortlisted candidates in an
        open process, and old records with no dates, are kept.
        """
        due = []
        for candidate in self._store.list_candidates():
            ended = self._process_end(candidate)
            if ended is None:
                continue
            reason, since = ended
            if now - datetime.fromisoformat(since) > timedelta(days=days):
                due.append({"candidate_id": candidate.candidate_id, "reason": reason, "since": since})
        return due

    def _process_end(self, candidate: StoredCandidate) -> tuple[str, str] | None:
        applications = self._store.applications_of(candidate.candidate_id)
        history = self._status_store.history_for(candidate.candidate_id)
        if applications:
            postings = [self._store.get_posting(a.job_id) for a in applications]
            if all(p is not None and p.status == "closed" and p.closed_at for p in postings):
                return "postings_closed", max(p.closed_at for p in postings)
            return None
        if history:
            latest = {job: (status, at) for job, status, at in history}
            if all(status == "rejected" for status, _ in latest.values()):
                return "rejected", max(at for _, at in latest.values())
            return None
        return ("pool_inactive", candidate.created_at) if candidate.created_at else None

    def reveal_identity(self, candidate_id: str, reviewer: str) -> IdentityRecord:
        if self._store.get_candidate(candidate_id) is None:
            raise ScreenerError("candidate_not_found")
        self._audit.record("screener.identity_revealed", candidate_id=candidate_id, reviewer=reviewer)
        record = self._identity.get(candidate_id) or IdentityRecord(candidate_id=candidate_id)
        return record.model_copy(update={"contacts": self._identity.contacts_for(candidate_id)})


def _posting_offer(posting: JobPosting) -> JobOffer:
    return JobOffer(job_id=posting.job_id, title=posting.details.title, requirements=posting.requirements)


def _letter_excerpts(application: Application) -> list[str]:
    return [f"[cover letter] {line}" for line in application.injection_excerpts]


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
