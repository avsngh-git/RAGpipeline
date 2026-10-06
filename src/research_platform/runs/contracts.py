"""Typed request, result, and budget contracts for research runs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_platform.llm.types import CallKind, DecodingSettings, ModelIdentity

_CONFIGURATION_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_EVIDENCE_HANDLE_PATTERN = r"^E[1-9][0-9]*$"
_CLAIM_ID_PATTERN = r"^claim-[1-9][0-9]*$"
UNINGESTED_SIMILARITY_THRESHOLD = 0.5


class _ContractModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class ResearchMode(StrEnum):
    """Research workflow requested for a run."""

    QUICK = "quick"
    DEEP_RESEARCH = "deep_research"


class RunStatus(StrEnum):
    """Lifecycle state of a research run."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_INGESTION = "waiting_for_ingestion"
    COMPLETED = "completed"
    FAILED = "failed"


class AnswerOutcome(StrEnum):
    """Evidence outcome assigned to a completed answer."""

    ANSWERED = "answered"
    PARTIALLY_SUPPORTED = "partially_supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class FailureCategory(StrEnum):
    """Stable category for a terminal run failure."""

    MODEL_UNAVAILABLE = "model_unavailable"
    INVALID_MODEL_OUTPUT = "invalid_model_output"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT = "timeout"
    RETRIEVAL_ERROR = "retrieval_error"
    RESUME_EXHAUSTED = "resume_exhausted"
    CONFIGURATION_CHANGED = "configuration_changed"
    INTERNAL = "internal"


class SupportLabel(StrEnum):
    """Evidence support recorded for a claim.

    Claims kept by quote verification are recorded as ``supported``; ``partial`` and
    ``unsupported`` remain for runs judged by the earlier LLM support judge.
    """

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class RunBudgets(_ContractModel):
    """Hard limits applied to one research run."""

    max_plan_rounds: int = Field(3, ge=1, le=10)
    max_actions_per_plan: int = Field(4, ge=1, le=10)
    max_tool_calls: int = Field(12, ge=1, le=50)
    max_citation_depth: int = Field(2, ge=0, le=3)
    max_evidence_passages: int = Field(40, ge=1, le=100)
    max_synthesis_tokens: int = Field(8000, ge=500, le=32000)
    max_model_retries: int = Field(2, ge=0, le=5)
    max_active_seconds: float = Field(1800.0, gt=0, le=3600)
    max_resumes: int = Field(2, ge=0, le=5)
    max_papers_per_wait: int = Field(5, ge=1, le=20)
    max_ingestion_wait_seconds: float = Field(900.0, gt=0, le=3600)


class ResearchFilters(_ContractModel):
    """Optional publication-year filter range."""

    year_from: int | None = Field(None, ge=1900, le=2100)
    year_to: int | None = Field(None, ge=1900, le=2100)

    @model_validator(mode="after")
    def validate_year_range(self) -> ResearchFilters:
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from must be less than or equal to year_to")
        return self


class ResearchRequest(_ContractModel):
    """Validated request to start a research run."""

    question: str
    mode: ResearchMode
    snapshot_id: UUID | None = None
    filters: ResearchFilters = Field(
        default_factory=lambda: ResearchFilters.model_construct()
    )

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        question = value.strip()
        if not 3 <= len(question) <= 2000:
            raise ValueError("question must contain 3 to 2000 characters")
        return question


class EvidenceCitation(_ContractModel):
    """A run-local evidence handle and its durable identifiers."""

    handle: str = Field(pattern=_EVIDENCE_HANDLE_PATTERN)
    chunk_id: str
    paper_id: str


class ClaimResult(_ContractModel):
    """One answer claim, the evidence cited for it and the quote it was checked against.

    ``quote`` is the passage text the claim was verified against; runs from before
    quote verification have none.
    """

    claim_id: str = Field(pattern=_CLAIM_ID_PATTERN)
    text: str = Field(min_length=1, max_length=1000)
    quote: str | None = Field(None, min_length=1, max_length=1000)
    evidence: tuple[EvidenceCitation, ...] = Field(min_length=1)
    support: SupportLabel


class ClaimVerdict(StrEnum):
    """Code verification result for one drafted claim."""

    KEPT = "kept"
    UNKNOWN_HANDLE = "unknown_handle"
    NOT_SHOWN = "not_shown"
    FAILED_CHECKS = "failed_checks"


class DraftClaimOutcome(_ContractModel):
    """One drafted claim and the verdict code verification gave it."""

    ordinal: int = Field(ge=1)
    handle: str
    quote: str
    text: str
    verdict: ClaimVerdict
    failed_checks: tuple[str, ...] = ()
    chunk_id: str | None = None
    paper_id: str | None = None


class SynthesisSummary(_ContractModel):
    """What the synthesis call saw and decided, without text."""

    model_declared_insufficient: bool
    relevant_handles: tuple[str, ...] = ()
    packed_handles: tuple[str, ...] = ()
    omitted_handles: tuple[str, ...] = ()
    drafted: int = Field(0, ge=0)


class PaperSummary(_ContractModel):
    """Compact paper metadata included in a run result."""

    paper_id: str
    title: str | None = None
    publication_year: int | None = None


class RunProvenance(_ContractModel):
    """Effective configuration, model information and catalog diagnostics for a run."""

    snapshot_id: UUID
    retrieval_profile_id: str
    configuration_id: str
    code_revision: str
    model: ModelIdentity
    thinking: dict[CallKind, bool]
    prompt_versions: dict[str, str]
    budgets: RunBudgets
    trace_id: str
    generation: int | None = Field(None, ge=1)
    retrieval_settings_id: str | None = None
    uningested_similarity_threshold: float | None = Field(
        None,
        ge=-1,
        le=1,
        description="Uncalibrated threshold for the metadata-only paper diagnostic.",
    )
    uningested_candidates: tuple[PaperSummary, ...] = ()
    provenance_version: int = Field(1, ge=1)
    prompt_fingerprints: dict[str, str] = Field(default_factory=dict)
    tool_schema_digest: str | None = None
    decoding: DecodingSettings | None = None
    generation_configuration_id: str | None = None

    @field_validator("configuration_id")
    @classmethod
    def validate_configuration_id(cls, value: str) -> str:
        if not _CONFIGURATION_ID_PATTERN.fullmatch(value):
            raise ValueError("configuration_id must be a sha256 identifier")
        return value


class RunUsage(_ContractModel):
    """Measured budget use and dropped-claim counts for a run."""

    plan_rounds: int = Field(0, ge=0)
    tool_calls: int = Field(0, ge=0)
    model_calls: int = Field(0, ge=0)
    active_seconds: float = Field(0.0, ge=0)
    resumes: int = Field(0, ge=0)
    # Claims citing an unknown or unshown handle, and claims that failed verification.
    rejected_claims: int = Field(0, ge=0)
    unsupported_claims: int = Field(0, ge=0)


class ResearchRunView(_ContractModel):
    """Public view of the status and result of a research run."""

    run_id: UUID
    status: RunStatus
    mode: ResearchMode
    question: str
    answer: str | None = None
    answer_outcome: AnswerOutcome | None = None
    claims: tuple[ClaimResult, ...] = ()
    papers: tuple[PaperSummary, ...] = ()
    uningested_candidates: tuple[PaperSummary, ...] = ()
    failure_category: FailureCategory | None = None
    error_message: str | None = None
    provenance: RunProvenance | None = None
    generation: int | None = Field(
        None, ge=1, description="Current generation; provenance keeps the starting one."
    )
    usage: RunUsage = Field(default_factory=lambda: RunUsage.model_construct())
    created_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> ResearchRunView:
        if self.status is RunStatus.COMPLETED:
            if self.answer_outcome is None or self.failure_category is not None:
                raise ValueError(
                    "completed runs require an answer outcome and no failure category"
                )
        elif self.status is RunStatus.FAILED:
            if self.failure_category is None or self.answer_outcome is not None:
                raise ValueError(
                    "failed runs require a failure category and no answer outcome"
                )
        elif (
            self.answer_outcome is not None
            or self.failure_category is not None
            or self.claims
        ):
            raise ValueError(
                "queued and running runs cannot have outcomes, failures, or claims"
            )
        return self


def configuration_id(payload: Mapping[str, object]) -> str:
    """Return a stable SHA-256 identifier for a JSON-compatible payload."""
    serialized = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"
