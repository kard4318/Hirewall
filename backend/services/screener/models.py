# Data models used by the screener service
"""Data contracts for semantic matching and the combined ranking.

Candidates arrive here already sanitized: pseudonymous id, visible text only,
no name, email, phone, photo, age or address. Hidden text must be stripped
upstream, because semantic similarity is exactly what keyword stuffing targets.
Outputs identify candidates by candidate_id only.
"""
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

RequirementKind = Literal["required", "preferred", "responsibility"]
SectionKind = Literal["summary", "experience", "education", "project", "skills", "other"]
Criterion = Literal["semantic", "rubric", "experience", "graph"]


class Requirement(BaseModel):
    text: str = Field(min_length=3)
    kind: RequirementKind = "required"


class JobOffer(BaseModel):
    job_id: str
    title: str
    requirements: list[Requirement] = Field(min_length=1)


class ResumeSection(BaseModel):
    kind: SectionKind
    text: str


class CandidateDocument(BaseModel):
    candidate_id: str            # pseudonym, never the real name
    sections: list[ResumeSection]
    injection_flag: bool = False  # set by the sanitization pipeline


class RequirementEvidence(BaseModel):
    requirement: str
    kind: RequirementKind
    score: float                 # calibrated, 0..1
    raw_similarity: float        # cosine, for debugging and calibration
    best_chunk_id: str | None    # resolve with SemanticIndex.chunk_text()


class SemanticMatch(BaseModel):
    candidate_id: str
    rank: int
    score: float                 # weighted mean of calibrated scores, 0..1
    requirements_met: int
    requirements_total: int
    injection_flag: bool
    evidence: list[RequirementEvidence]


class SemanticRanking(BaseModel):
    """One ranking run. Store it as-is so the result can be reproduced and audited."""
    job_id: str
    model_id: str
    config: dict
    matches: list[SemanticMatch]


class ExperienceResult(BaseModel):
    """Job-relevant experience, computed from dated positions in experience sections."""
    relevant_years: float         # in positions that mention the job's skills or role
    total_years: float            # all dated positions, overlaps counted once
    required_years: float | None  # None = the job states no requirement
    score: float | None           # 0..1, None = not applicable (no requirement)
    positions_dated: int
    positions_relevant: int
    explanation: str


class CriterionScores(BaseModel):
    """Per-criterion scores in 0..1. None = not applicable, left out of the total."""
    semantic: float | None
    experience: float | None
    graph: float | None
    rubric: float | None = None


class RubricResult(BaseModel):
    """The model's judgement. `score` is computed by code from the three sub-scores."""
    score: float | None = None         # mean of the sub-scores / 10, None = not applicable
    skills_coverage: int | None = None
    related_experience: int | None = None
    field_closeness: int | None = None
    skills_text: str = ""              # model text: display as plain text
    experience_text: str = ""
    field_text: str = ""
    reason_code: str | None = None     # why the score is None
    prompt_version: str | None = None


class EvidenceChunk(BaseModel):
    chunk_id: str
    text: str


class RankedCandidate(BaseModel):
    candidate_id: str
    rank: int
    total_score: float                 # weighted mean over applied criteria, 0..1
    scores: CriterionScores            # kept separate so large gaps can be flagged later
    applied_criteria: list[Criterion]
    weights_used: dict[str, float]     # renormalized over applied criteria, sums to 1
    matched_skills: list[str]          # display only: job skills found in the resume
    missing_skills: list[str]          # display only: job skills not found
    additional_skills: list[str]       # display only, never scored
    experience: ExperienceResult
    injection_flag: bool
    requirements_met: int
    requirements_total: int
    evidence: list[RequirementEvidence]
    rubric: RubricResult = Field(default_factory=RubricResult)
    evidence_chunks: list[EvidenceChunk] = Field(default_factory=list)
    injection_excerpts: list[str] = Field(default_factory=list)  # never used in scoring
    hidden_text_removed: bool = False                            # never used in scoring
    profile: str = "Other"                                       # display only, never used in scoring


class CombinedRanking(BaseModel):
    """One combined ranking run. Store it as-is so it can be reproduced and audited."""
    job_id: str
    as_of: date                        # reference date for "present" in resumes
    required_years: float | None       # parsed from the job, None = no requirement
    weights_config: dict[str, float]   # configured weights, before renormalization
    semantic_model_id: str
    semantic_config: dict
    graph_scorer: str
    candidates: list[RankedCandidate]


class Position(BaseModel):
    title: str = Field(default="", max_length=200)
    organization: str = Field(default="", max_length=200)
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)


class EducationEntry(BaseModel):
    degree: str = Field(default="", max_length=200)
    institution: str = Field(default="", max_length=200)
    year: str | None = Field(default=None, max_length=40)


class CertificationEntry(BaseModel):
    name: str = Field(default="", max_length=200)
    issuer: str = Field(default="", max_length=200)
    year: str | None = Field(default=None, max_length=40)


class CandidateProfile(BaseModel):
    """Structured view of a resume, for display and for the rubric prompt. Holds no identity."""
    current_title: str | None = Field(default=None, max_length=200)
    positions: list[Position] = Field(default_factory=list, max_length=40)
    skills: list[str] = Field(default_factory=list, max_length=100)
    education: list[EducationEntry] = Field(default_factory=list, max_length=20)
    certifications: list[CertificationEntry] = Field(default_factory=list, max_length=30)


class StoredCandidate(BaseModel):
    """What the screener keeps about a candidate. Identity lives in a separate store."""
    candidate_id: str
    content_hash: str
    source: Literal["upload", "demo"]
    document: CandidateDocument
    profile: CandidateProfile | None = None
    extraction_failed: bool = False
    injection_excerpts: list[str] = Field(default_factory=list)
    hidden_text_removed: bool = False
    family: str = "Other"


class CandidateSummary(BaseModel):
    candidate_id: str
    source: str
    profile: str
    current_title: str | None
    skills: list[str]
    injection_flag: bool
    hidden_text_removed: bool
    extraction_failed: bool


class FileResult(BaseModel):
    """One uploaded file's outcome. File names are never stored: they often hold the candidate's name."""
    index: int
    status: Literal["accepted", "duplicate", "rejected", "failed"]
    reason_code: str | None = None
    candidate_id: str | None = None
    injection_flag: bool = False
    hidden_text_removed: bool = False
    extraction_failed: bool = False


class IngestionTask(BaseModel):
    task_id: str
    status: Literal["queued", "running", "done", "failed"] = "queued"
    total: int = 0
    done: int = 0
    files: list[FileResult] = Field(default_factory=list)


class ScreeningRun(BaseModel):
    """One scoring run and its progress. Store it as-is so it can be reproduced and audited."""
    run_id: str
    job_id: str
    status: Literal["queued", "running", "done", "failed"] = "queued"
    total: int = 0
    done: int = 0
    pending: list[str] = Field(default_factory=list)
    candidates: list[RankedCandidate] = Field(default_factory=list)
    as_of: date
    weights_config: dict[str, float] = Field(default_factory=dict)
    required_years: float | None = None
    semantic_model_id: str | None = None
    llm_model: str | None = None
    rubric_prompt_version: str | None = None
    reason_code: str | None = None
    statuses: dict[str, str] = Field(default_factory=dict)  # filled when read, from the executor's records


class ApplicantContact(BaseModel):
    """What an applicant typed in the form. Kept per application: it never replaces the identity found in a CV."""
    reference_id: str
    job_id: str
    full_name: str
    email: str
    consent_at: str


class IdentityRecord(BaseModel):
    candidate_id: str
    full_name: str | None = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)
    contacts: list[ApplicantContact] = Field(default_factory=list)


class RecordPayload(BaseModel):
    job_id: str
    run_id: str
    candidate_ids: list[str]


class ProposedRecordAction(BaseModel):
    """A shortlist or rejection waiting for a human. Built by code; nothing in it comes from a model or a resume."""
    action_type: Literal["record_shortlist", "record_rejection"]
    payload: RecordPayload
    in_reply_to: str              # scope key: a newer pending proposal for the same job supersedes this one
    payload_hash: str
    idempotency_key: str


_Line = Annotated[str, StringConstraints(max_length=500)]
ContractType = Literal["internship", "full_time", "part_time", "fixed_term", "freelance", "other"]
RemoteMode = Literal["onsite", "hybrid", "remote"]


class JobPostingDetails(BaseModel):
    """A job offer as structured data. Values are copied as written, never invented."""
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    contract_type: ContractType | None = None
    location: str | None = Field(default=None, max_length=200)
    remote: RemoteMode | None = None
    duration: str | None = Field(default=None, max_length=100)
    start_date: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    responsibilities: list[_Line] = Field(default_factory=list, max_length=40)
    required_skills: list[_Line] = Field(default_factory=list, max_length=40)
    preferred_skills: list[_Line] = Field(default_factory=list, max_length=40)
    min_years_experience: float | None = Field(default=None, ge=0, le=50)
    education_level: str | None = Field(default=None, max_length=200)
    languages: list[_Line] = Field(default_factory=list, max_length=20)
    benefits: list[_Line] = Field(default_factory=list, max_length=30)
    application_deadline: str | None = Field(default=None, max_length=100)


class JobPosting(BaseModel):
    job_id: str
    status: Literal["draft", "published", "closed"] = "draft"
    details: JobPostingDetails
    requirements: list[Requirement] = Field(default_factory=list)  # derived in code from the details
    extraction_failed: bool = False
    flagged_requirements: list[str] = Field(default_factory=list)  # protected attributes: HR decides
    injection_excerpts: list[str] = Field(default_factory=list)
    hidden_text_removed: bool = False
    source_hash: str | None = None
    created_at: str
    published_at: str | None = None


class CoverLetterProfile(BaseModel):
    """Display only: it never feeds the ranking or the rubric."""
    model_config = ConfigDict(extra="forbid")

    motivation_summary: str | None = Field(default=None, max_length=2000)
    skills_mentioned: list[_Line] = Field(default_factory=list, max_length=50)
    relevant_experiences: list[_Line] = Field(default_factory=list, max_length=20)
    availability: str | None = Field(default=None, max_length=200)
    start_date: str | None = Field(default=None, max_length=100)
    desired_duration: str | None = Field(default=None, max_length=100)
    languages: list[_Line] = Field(default_factory=list, max_length=20)
    mobility: str | None = Field(default=None, max_length=200)


class Application(BaseModel):
    """One candidate applying to one job. Flags live here so they stay with this application."""
    application_id: str
    job_id: str
    candidate_id: str
    cover_letter: CoverLetterProfile | None = None
    cover_letter_text: str | None = None  # pseudonymized, for when the model could not extract a profile
    cover_letter_failed: bool = False
    injection_excerpts: list[str] = Field(default_factory=list)
    hidden_text_removed: bool = False
    submitted_at: str
    source: Literal["applicant", "hr_upload"]
