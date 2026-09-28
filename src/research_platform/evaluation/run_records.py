"""Versioned local records for replayable calibration search runs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast
from uuid import UUID, uuid4

from research_platform.evaluation.calibration import CalibrationDataset
from research_platform.evaluation.scoring import (
    HitGradeCounts,
    MetricValue,
    QueryFamilyScore,
    RankingMetrics,
)
from research_platform.evaluation.source_alignment import SourceAlignmentDataset
from research_platform.ingestion.evidence import EvidenceKind, SourceLocation
from research_platform.ingestion.identity import DocumentVersionKind, is_valid_paper_id
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    PaperHit,
    PaperMetadataHit,
    RankedComponent,
    RetrievalMode,
    SearchFilters,
    SearchOperation,
    SearchRankingInterpretation,
    SearchRequest,
    SearchResponse,
    SearchResultStatus,
)

_RUN_SCHEMA_VERSION = 3
_HASH = re.compile(r"^[0-9a-f]{64}$")
_CODE_REVISION = re.compile(r"^[0-9a-f]{7,40}$")
_FAILURE_CATEGORIES = {
    "timeout",
    "transport",
    "backend",
    "validation",
    "resource",
    "cancelled",
    "other",
}
_LATENCY_KINDS = {"cold", "warm"}
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_RUN_ROOT = _REPOSITORY_ROOT / "local-reference" / "phase2-runs"

FailureCategory = Literal[
    "timeout", "transport", "backend", "validation", "resource", "cancelled", "other"
]
LatencyKind = Literal["cold", "warm"]
AttemptStatus = Literal["success", "degraded", "failed"]
RunStatus = Literal["complete", "degraded", "partial", "failed"]
PaperResultKind = Literal["paper", "paper_metadata"]


class RunRecordError(ValueError):
    """A run record does not satisfy its versioned schema or lineage."""


@dataclass(frozen=True)
class HardwareDescriptor:
    """Host hardware facts without user, host, or device serial identifiers."""

    platform_system: str
    platform_release: str
    machine_architecture: str
    processor: str
    python_version: str
    logical_cpu_count: int
    ram_bytes: int | None = None
    accelerator_name: str | None = None
    accelerator_memory_bytes: int | None = None

    def __post_init__(self) -> None:
        for name, text_value in (
            ("platform_system", self.platform_system),
            ("platform_release", self.platform_release),
            ("machine_architecture", self.machine_architecture),
            ("processor", self.processor),
            ("python_version", self.python_version),
        ):
            if not isinstance(text_value, str) or not text_value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if (
            isinstance(self.logical_cpu_count, bool)
            or not isinstance(self.logical_cpu_count, int)
            or self.logical_cpu_count <= 0
        ):
            raise ValueError("logical_cpu_count must be a positive integer")
        for name, memory_bytes in (
            ("ram_bytes", self.ram_bytes),
            ("accelerator_memory_bytes", self.accelerator_memory_bytes),
        ):
            if memory_bytes is not None and (
                isinstance(memory_bytes, bool)
                or not isinstance(memory_bytes, int)
                or memory_bytes <= 0
            ):
                raise ValueError(f"{name} must be a positive integer or null")
        if self.accelerator_name is not None and (
            not isinstance(self.accelerator_name, str)
            or not self.accelerator_name.strip()
        ):
            raise ValueError("accelerator_name must be a non-empty string or null")

    @classmethod
    def capture_host(
        cls,
        *,
        ram_bytes: int | None = None,
        accelerator_name: str | None = None,
        accelerator_memory_bytes: int | None = None,
    ) -> HardwareDescriptor:
        """Capture platform and CPU facts; optional memory/device data is supplied."""
        return cls(
            platform_system=platform.system() or "unknown",
            platform_release=platform.release() or "unknown",
            machine_architecture=platform.machine() or "unknown",
            processor=platform.processor() or platform.machine() or "unknown",
            python_version=platform.python_version(),
            logical_cpu_count=os.cpu_count() or 1,
            ram_bytes=ram_bytes,
            accelerator_name=accelerator_name,
            accelerator_memory_bytes=accelerator_memory_bytes,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "platform_system": self.platform_system,
            "platform_release": self.platform_release,
            "machine_architecture": self.machine_architecture,
            "processor": self.processor,
            "python_version": self.python_version,
            "logical_cpu_count": self.logical_cpu_count,
            "ram_bytes": self.ram_bytes,
            "accelerator_name": self.accelerator_name,
            "accelerator_memory_bytes": self.accelerator_memory_bytes,
        }


@dataclass(frozen=True)
class EvidenceResultRecord:
    """Returned evidence identity, rank, provenance, and raw component scores."""

    rank: int
    chunk_id: str
    source_evidence_ids: tuple[str, ...]
    paper_id: str
    document_id: UUID
    document_version: str
    document_version_kind: DocumentVersionKind
    extraction_id: UUID
    chunking_configuration_id: str | None
    kind: EvidenceKind
    source_location: SourceLocation
    component_scores: ComponentScores

    def __post_init__(self) -> None:
        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 1
        ):
            raise ValueError("rank must be a positive integer")
        if not isinstance(self.chunk_id, str) or not self.chunk_id.strip():
            raise ValueError("chunk_id must be non-empty")
        if (
            not isinstance(self.source_evidence_ids, tuple)
            or not self.source_evidence_ids
            or any(
                not isinstance(value, str) or not value.strip()
                for value in self.source_evidence_ids
            )
        ):
            raise ValueError("source_evidence_ids must contain source identities")
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if not isinstance(self.document_id, UUID) or not isinstance(
            self.extraction_id, UUID
        ):
            raise ValueError("document_id and extraction_id must be UUIDs")
        if not isinstance(self.document_version, str) or not self.document_version:
            raise ValueError("document_version must be non-empty")
        if not isinstance(
            self.document_version_kind, str
        ) or self.document_version_kind not in {
            "published",
            "preprint",
            "other",
            "unknown",
        }:
            raise ValueError("document_version_kind is unsupported")
        if self.chunking_configuration_id is not None and (
            not isinstance(self.chunking_configuration_id, str)
            or not self.chunking_configuration_id.startswith("sha256:")
            or not _HASH.fullmatch(
                self.chunking_configuration_id.removeprefix("sha256:")
            )
        ):
            raise ValueError("chunking_configuration_id must be a SHA-256 identity")
        if not isinstance(self.kind, str) or self.kind not in {
            "text",
            "table",
            "table_row_group",
            "caption",
            "figure",
            "equation",
        }:
            raise ValueError("kind is unsupported")
        if not isinstance(self.source_location, SourceLocation):
            raise ValueError("source_location must be a SourceLocation")
        _validate_component_scores(self.component_scores)

    def to_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "chunk_id": self.chunk_id,
            "source_evidence_ids": list(self.source_evidence_ids),
            "paper_id": self.paper_id,
            "document_id": str(self.document_id),
            "document_version": self.document_version,
            "document_version_kind": self.document_version_kind,
            "extraction_id": str(self.extraction_id),
            "chunking_configuration_id": self.chunking_configuration_id,
            "kind": self.kind,
            "source_location": self.source_location.to_dict(),
            "component_scores": _component_scores_dict(self.component_scores),
        }


@dataclass(frozen=True)
class PaperResultRecord:
    """Returned paper identity and any evidence bundled with its paper hit."""

    rank: int
    paper_id: str
    result_kind: PaperResultKind
    component_scores: ComponentScores
    supporting_evidence: tuple[EvidenceResultRecord, ...] = ()

    def __post_init__(self) -> None:
        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 1
        ):
            raise ValueError("rank must be a positive integer")
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if not isinstance(self.result_kind, str) or self.result_kind not in {
            "paper",
            "paper_metadata",
        }:
            raise ValueError("result_kind is unsupported")
        _validate_component_scores(self.component_scores)
        if not isinstance(self.supporting_evidence, tuple) or any(
            not isinstance(item, EvidenceResultRecord)
            for item in self.supporting_evidence
        ):
            raise ValueError("supporting_evidence must contain evidence records")
        if any(item.paper_id != self.paper_id for item in self.supporting_evidence):
            raise ValueError("supporting evidence must belong to this paper")
        if self.result_kind == "paper_metadata" and self.supporting_evidence:
            raise ValueError("metadata results cannot contain supporting evidence")

    def to_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "paper_id": self.paper_id,
            "result_kind": self.result_kind,
            "component_scores": _component_scores_dict(self.component_scores),
            "supporting_evidence": [
                item.to_dict() for item in self.supporting_evidence
            ],
        }


@dataclass(frozen=True)
class SearchAttemptRecord:
    """One successful, degraded, or failed search request."""

    attempt_id: UUID
    operation: SearchOperation
    snapshot_id: UUID
    retrieval_profile_id: str
    requested_mode: RetrievalMode
    filters: SearchFilters
    limit: int
    latency_ms: float
    latency_kind: LatencyKind
    status: AttemptStatus
    request_id: str | None = None
    effective_mode: RetrievalMode | None = None
    effective_configuration_id: str | None = None
    warning_count: int = 0
    truncated: bool = False
    omitted_count: int = 0
    eligible_count: int | None = None
    result_status: SearchResultStatus | None = None
    ranking_interpretation: SearchRankingInterpretation | None = None
    paper_results: tuple[PaperResultRecord, ...] = ()
    evidence_results: tuple[EvidenceResultRecord, ...] = ()
    failure_category: FailureCategory | None = None
    peak_ram_bytes: int | None = None
    peak_accelerator_memory_bytes: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_id, UUID) or not isinstance(
            self.snapshot_id, UUID
        ):
            raise ValueError("attempt_id and snapshot_id must be UUIDs")
        if not isinstance(self.operation, SearchOperation):
            raise ValueError("operation must be a SearchOperation")
        if (
            not isinstance(self.retrieval_profile_id, str)
            or not self.retrieval_profile_id.startswith("sha256:")
            or not _HASH.fullmatch(self.retrieval_profile_id.removeprefix("sha256:"))
        ):
            raise ValueError("retrieval_profile_id must be a SHA-256 identity")
        if not isinstance(self.requested_mode, RetrievalMode):
            raise ValueError("requested_mode must be a RetrievalMode")
        if not isinstance(self.filters, SearchFilters):
            raise ValueError("filters must be SearchFilters")
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or self.limit <= 0
        ):
            raise ValueError("limit must be a positive integer")
        if (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, (int, float))
            or not math.isfinite(self.latency_ms)
            or self.latency_ms < 0
        ):
            raise ValueError("latency_ms must be finite and non-negative")
        if (
            not isinstance(self.latency_kind, str)
            or self.latency_kind not in _LATENCY_KINDS
        ):
            raise ValueError("latency_kind must be cold or warm")
        if not isinstance(self.status, str) or self.status not in {
            "success",
            "degraded",
            "failed",
        }:
            raise ValueError("status is unsupported")
        if self.request_id is not None and (
            not isinstance(self.request_id, str) or not self.request_id.strip()
        ):
            raise ValueError("request_id must be non-empty or null")
        if self.effective_mode is not None and not isinstance(
            self.effective_mode, RetrievalMode
        ):
            raise ValueError("effective_mode must be a RetrievalMode or null")
        if self.effective_configuration_id is not None and (
            not isinstance(self.effective_configuration_id, str)
            or not self.effective_configuration_id.startswith("sha256:")
            or not _HASH.fullmatch(
                self.effective_configuration_id.removeprefix("sha256:")
            )
        ):
            raise ValueError("effective_configuration_id must be a SHA-256 identity")
        for name, count_value in (
            ("warning_count", self.warning_count),
            ("omitted_count", self.omitted_count),
        ):
            if (
                isinstance(count_value, bool)
                or not isinstance(count_value, int)
                or count_value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.truncated, bool):
            raise ValueError("truncated must be a boolean")
        if self.eligible_count is not None and (
            isinstance(self.eligible_count, bool)
            or not isinstance(self.eligible_count, int)
            or self.eligible_count < 0
        ):
            raise ValueError("eligible_count must be a non-negative integer or null")
        if self.result_status is not None and not isinstance(
            self.result_status, SearchResultStatus
        ):
            raise ValueError("result_status must be a SearchResultStatus or null")
        if self.ranking_interpretation is not None and not isinstance(
            self.ranking_interpretation, SearchRankingInterpretation
        ):
            raise ValueError(
                "ranking_interpretation must be SearchRankingInterpretation or null"
            )
        for name, memory_bytes in (
            ("peak_ram_bytes", self.peak_ram_bytes),
            ("peak_accelerator_memory_bytes", self.peak_accelerator_memory_bytes),
        ):
            if memory_bytes is not None and (
                isinstance(memory_bytes, bool)
                or not isinstance(memory_bytes, int)
                or memory_bytes <= 0
            ):
                raise ValueError(f"{name} must be a positive integer or null")
        if self.failure_category is not None and (
            not isinstance(self.failure_category, str)
            or self.failure_category not in _FAILURE_CATEGORIES
        ):
            raise ValueError("failure_category is unsupported")
        if self.status == "failed":
            if self.failure_category is None:
                raise ValueError("failed attempts require a failure_category")
            if (
                self.request_id is not None
                or self.effective_mode is not None
                or self.effective_configuration_id is not None
                or self.eligible_count is not None
                or self.result_status is not None
                or self.ranking_interpretation is not None
                or self.paper_results
                or self.evidence_results
            ):
                raise ValueError("failed attempts cannot contain response data")
        elif (
            self.failure_category is not None
            or self.request_id is None
            or self.effective_mode is None
            or self.effective_configuration_id is None
            or self.eligible_count is None
            or self.result_status is None
            or self.ranking_interpretation is None
        ):
            raise ValueError("successful attempts require response data and no failure")
        elif self.status != (
            "degraded" if self.effective_mode is not self.requested_mode else "success"
        ):
            raise ValueError("attempt status does not match its effective response")
        if not isinstance(self.paper_results, tuple) or any(
            not isinstance(item, PaperResultRecord) for item in self.paper_results
        ):
            raise ValueError("paper_results must contain PaperResultRecord values")
        if not isinstance(self.evidence_results, tuple) or any(
            not isinstance(item, EvidenceResultRecord) for item in self.evidence_results
        ):
            raise ValueError(
                "evidence_results must contain EvidenceResultRecord values"
            )
        paper_ranks = [item.rank for item in self.paper_results]
        evidence_ranks = [item.rank for item in self.evidence_results]
        if len(set(paper_ranks)) != len(paper_ranks):
            raise ValueError("paper result ranks must be unique")
        if len(set(evidence_ranks)) != len(evidence_ranks):
            raise ValueError("evidence result ranks must be unique")
        if self.eligible_count is not None:
            result_count = len(self.paper_results) + len(self.evidence_results)
            if result_count > self.eligible_count:
                raise ValueError("returned result count cannot exceed eligible_count")
            expected_result_status = (
                SearchResultStatus.NO_ELIGIBLE_RECORDS
                if self.eligible_count == 0
                else SearchResultStatus.NO_CANDIDATES_RETURNED
                if result_count == 0
                else SearchResultStatus.RANKED_CANDIDATES
            )
            if self.result_status is not expected_result_status:
                raise ValueError("result_status does not match eligibility and results")
            if (
                self.ranking_interpretation
                is not SearchRankingInterpretation.RANKING_ONLY
            ):
                raise ValueError("search attempts record ranking-only interpretation")
        if (
            len(self.paper_results) > self.limit
            or len(self.evidence_results) > self.limit
        ):
            raise ValueError("returned results cannot exceed the requested limit")
        if self.operation is SearchOperation.EVIDENCE_SEARCH and self.paper_results:
            raise ValueError("evidence-search attempts cannot contain paper results")
        if self.operation is SearchOperation.PAPER_METADATA and self.evidence_results:
            raise ValueError("paper-metadata attempts cannot contain evidence results")
        if self.operation is SearchOperation.PAPER_METADATA and any(
            item.result_kind != "paper_metadata" for item in self.paper_results
        ):
            raise ValueError("paper-metadata results have an invalid result kind")
        if self.operation is SearchOperation.PAPER_SEARCH and self.evidence_results:
            raise ValueError("paper-search attempts cannot contain evidence results")
        if self.operation is SearchOperation.PAPER_SEARCH and any(
            item.result_kind != "paper" for item in self.paper_results
        ):
            raise ValueError("paper-search results have an invalid result kind")

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt_id": str(self.attempt_id),
            "operation": self.operation.value,
            "snapshot_id": str(self.snapshot_id),
            "retrieval_profile_id": self.retrieval_profile_id,
            "requested_mode": self.requested_mode.value,
            "effective_mode": (
                self.effective_mode.value if self.effective_mode else None
            ),
            "effective_configuration_id": self.effective_configuration_id,
            "filters": self.filters.to_dict(),
            "limit": self.limit,
            "latency_ms": self.latency_ms,
            "latency_kind": self.latency_kind,
            "status": self.status,
            "request_id": self.request_id,
            "warning_count": self.warning_count,
            "truncated": self.truncated,
            "omitted_count": self.omitted_count,
            "eligible_count": self.eligible_count,
            "result_status": (
                self.result_status.value if self.result_status is not None else None
            ),
            "ranking_interpretation": (
                self.ranking_interpretation.value
                if self.ranking_interpretation is not None
                else None
            ),
            "failure_category": self.failure_category,
            "peak_ram_bytes": self.peak_ram_bytes,
            "peak_accelerator_memory_bytes": self.peak_accelerator_memory_bytes,
            "paper_results": [item.to_dict() for item in self.paper_results],
            "evidence_results": [item.to_dict() for item in self.evidence_results],
        }


@dataclass(frozen=True)
class QueryRunRecord:
    """Versioned raw record for one calibrated query across search attempts."""

    run_id: UUID
    experiment_id: str | None
    comparison_id: str | None
    started_at: datetime
    calibration_dataset_id: str
    calibration_sha256: str
    split_policy_id: str
    family_id: str
    query_id: str
    split: str
    snapshot_id: UUID
    source_alignment_id: str
    source_alignment_sha256: str
    source_matching_policy_id: str
    scoring_policy_id: str
    code_revision: str
    working_tree_dirty: bool
    working_tree_diff_sha256: str | None
    hardware: HardwareDescriptor
    random_seed: int | None
    attempts: tuple[SearchAttemptRecord, ...]
    score: QueryFamilyScore | None = None
    schema_version: int = _RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != _RUN_SCHEMA_VERSION
        ):
            raise ValueError("unsupported query run schema version")
        if not isinstance(self.run_id, UUID) or not isinstance(self.snapshot_id, UUID):
            raise ValueError("run_id and snapshot_id must be UUIDs")
        if (
            not isinstance(self.started_at, datetime)
            or self.started_at.utcoffset() is None
        ):
            raise ValueError("started_at must be a timezone-aware datetime")
        if self.started_at.utcoffset() != timezone.utc.utcoffset(self.started_at):
            raise ValueError("started_at must be expressed in UTC")
        for name, value in (
            ("calibration_sha256", self.calibration_sha256),
            ("source_alignment_sha256", self.source_alignment_sha256),
        ):
            if not isinstance(value, str) or not _HASH.fullmatch(value):
                raise ValueError(f"{name} must be 64 lowercase hexadecimal digits")
        if not isinstance(self.code_revision, str) or not _CODE_REVISION.fullmatch(
            self.code_revision
        ):
            raise ValueError("code_revision must be a lowercase Git commit prefix")
        if not isinstance(self.working_tree_dirty, bool):
            raise ValueError("working_tree_dirty must be a boolean")
        if self.working_tree_dirty:
            if not isinstance(
                self.working_tree_diff_sha256, str
            ) or not _HASH.fullmatch(self.working_tree_diff_sha256):
                raise ValueError("dirty working trees require a diff checksum")
        elif self.working_tree_diff_sha256 is not None:
            raise ValueError("clean working trees cannot have a diff checksum")
        for name, value in (
            ("calibration_dataset_id", self.calibration_dataset_id),
            ("split_policy_id", self.split_policy_id),
            ("family_id", self.family_id),
            ("query_id", self.query_id),
            ("source_alignment_id", self.source_alignment_id),
            ("source_matching_policy_id", self.source_matching_policy_id),
            ("scoring_policy_id", self.scoring_policy_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.split, str) or self.split not in {
            "development",
            "held_out",
        }:
            raise ValueError("split must be development or held_out")
        if self.experiment_id is not None and (
            not isinstance(self.experiment_id, str) or not self.experiment_id.strip()
        ):
            raise ValueError("experiment_id must be non-empty or null")
        if self.comparison_id is not None and (
            not isinstance(self.comparison_id, str) or not self.comparison_id.strip()
        ):
            raise ValueError("comparison_id must be non-empty or null")
        if self.random_seed is not None and (
            isinstance(self.random_seed, bool)
            or not isinstance(self.random_seed, int)
            or self.random_seed < 0
        ):
            raise ValueError("random_seed must be non-negative or null")
        if not isinstance(self.hardware, HardwareDescriptor):
            raise ValueError("hardware must be a HardwareDescriptor")
        if not isinstance(self.attempts, tuple) or not self.attempts:
            raise ValueError("attempts must be a non-empty tuple")
        if any(not isinstance(item, SearchAttemptRecord) for item in self.attempts):
            raise ValueError("attempts must contain SearchAttemptRecord values")
        if len({item.attempt_id for item in self.attempts}) != len(self.attempts):
            raise ValueError("attempt IDs must be unique")
        if any(item.snapshot_id != self.snapshot_id for item in self.attempts):
            raise ValueError("all attempts must use the run snapshot")
        if self.source_matching_policy_id != "source-match-policy-v1":
            raise ValueError("unsupported source matching policy")
        if self.scoring_policy_id != "evaluation-scoring-policy-v1":
            raise ValueError("unsupported scoring policy")
        if self.score is not None:
            if not isinstance(self.score, QueryFamilyScore):
                raise ValueError("score must be a QueryFamilyScore or null")
            if (
                self.score.calibration_dataset_id != self.calibration_dataset_id
                or self.score.snapshot_id != self.snapshot_id
                or self.score.source_alignment_id != self.source_alignment_id
                or self.score.source_matching_policy_id
                != self.source_matching_policy_id
                or self.score.scoring_policy_id != self.scoring_policy_id
                or self.score.family_id != self.family_id
                or self.score.query_id != self.query_id
                or self.score.split != self.split
            ):
                raise ValueError("score lineage does not match the run record")

    @property
    def status(self) -> RunStatus:
        failed = sum(attempt.status == "failed" for attempt in self.attempts)
        if failed == len(self.attempts):
            return "failed"
        if failed:
            return "partial"
        if any(attempt.status == "degraded" for attempt in self.attempts):
            return "degraded"
        return "complete"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": str(self.run_id),
            "experiment_id": self.experiment_id,
            "comparison_id": self.comparison_id,
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "status": self.status,
            "calibration_dataset_id": self.calibration_dataset_id,
            "calibration_sha256": self.calibration_sha256,
            "split_policy_id": self.split_policy_id,
            "family_id": self.family_id,
            "query_id": self.query_id,
            "split": self.split,
            "snapshot_id": str(self.snapshot_id),
            "source_alignment_id": self.source_alignment_id,
            "source_alignment_sha256": self.source_alignment_sha256,
            "source_matching_policy_id": self.source_matching_policy_id,
            "scoring_policy_id": self.scoring_policy_id,
            "code_revision": self.code_revision,
            "working_tree_dirty": self.working_tree_dirty,
            "working_tree_diff_sha256": self.working_tree_diff_sha256,
            "hardware": self.hardware.to_dict(),
            "random_seed": self.random_seed,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "score": _score_dict(self.score) if self.score is not None else None,
        }


def successful_search_attempt(
    request: SearchRequest,
    response: (
        SearchResponse[PaperHit]
        | SearchResponse[PaperMetadataHit]
        | SearchResponse[EvidenceHit]
    ),
    *,
    attempt_id: UUID,
    latency_ms: float,
    latency_kind: LatencyKind,
    peak_ram_bytes: int | None = None,
    peak_accelerator_memory_bytes: int | None = None,
) -> SearchAttemptRecord:
    """Capture a response without query text, result text, or warning messages."""
    if request.snapshot_id != response.snapshot_id:
        raise RunRecordError("request and response snapshots differ")
    if request.retrieval_profile_id != response.retrieval_profile_id:
        raise RunRecordError("request and response profiles differ")
    if request.mode is not response.requested_mode:
        raise RunRecordError("request and response requested modes differ")
    paper_results: tuple[PaperResultRecord, ...] = ()
    evidence_results: tuple[EvidenceResultRecord, ...] = ()
    if request.operation is SearchOperation.EVIDENCE_SEARCH:
        if any(not isinstance(hit, EvidenceHit) for hit in response.hits):
            raise RunRecordError("evidence search returned a non-evidence result")
        evidence_response = cast(SearchResponse[EvidenceHit], response)
        evidence_results = tuple(
            _evidence_result(hit) for hit in evidence_response.hits
        )
    elif request.operation is SearchOperation.PAPER_SEARCH:
        if any(not isinstance(hit, PaperHit) for hit in response.hits):
            raise RunRecordError("paper search returned a non-paper result")
        paper_response = cast(SearchResponse[PaperHit], response)
        paper_results = tuple(_paper_result(hit) for hit in paper_response.hits)
    else:
        if any(not isinstance(hit, PaperMetadataHit) for hit in response.hits):
            raise RunRecordError("paper metadata search returned a non-metadata result")
        metadata_response = cast(SearchResponse[PaperMetadataHit], response)
        paper_results = tuple(_metadata_result(hit) for hit in metadata_response.hits)
    status: AttemptStatus = (
        "degraded" if response.effective_mode is not request.mode else "success"
    )
    return SearchAttemptRecord(
        attempt_id=attempt_id,
        operation=request.operation,
        snapshot_id=request.snapshot_id,
        retrieval_profile_id=request.retrieval_profile_id,
        requested_mode=request.mode,
        effective_mode=response.effective_mode,
        effective_configuration_id=response.effective_configuration_id,
        filters=request.filters,
        limit=request.limit,
        latency_ms=latency_ms,
        latency_kind=latency_kind,
        status=status,
        request_id=response.request_id,
        warning_count=len(response.warnings),
        truncated=response.truncated,
        omitted_count=response.omitted_count,
        eligible_count=response.eligible_count,
        result_status=response.result_status,
        ranking_interpretation=response.ranking_interpretation,
        paper_results=paper_results,
        evidence_results=evidence_results,
        peak_ram_bytes=peak_ram_bytes,
        peak_accelerator_memory_bytes=peak_accelerator_memory_bytes,
    )


def failed_search_attempt(
    request: SearchRequest,
    *,
    attempt_id: UUID,
    latency_ms: float,
    latency_kind: LatencyKind,
    failure_category: FailureCategory,
    peak_ram_bytes: int | None = None,
    peak_accelerator_memory_bytes: int | None = None,
) -> SearchAttemptRecord:
    """Capture a structured failure without an exception message or query text."""
    if (
        not isinstance(failure_category, str)
        or failure_category not in _FAILURE_CATEGORIES
    ):
        raise RunRecordError("failure_category is unsupported")
    return SearchAttemptRecord(
        attempt_id=attempt_id,
        operation=request.operation,
        snapshot_id=request.snapshot_id,
        retrieval_profile_id=request.retrieval_profile_id,
        requested_mode=request.mode,
        filters=request.filters,
        limit=request.limit,
        latency_ms=latency_ms,
        latency_kind=latency_kind,
        status="failed",
        failure_category=failure_category,
        peak_ram_bytes=peak_ram_bytes,
        peak_accelerator_memory_bytes=peak_accelerator_memory_bytes,
    )


def create_query_run_record(
    calibration: CalibrationDataset,
    alignments: SourceAlignmentDataset,
    *,
    family_id: str,
    query_id: str,
    calibration_sha256: str,
    source_alignment_sha256: str,
    code_revision: str,
    working_tree_dirty: bool,
    working_tree_diff_sha256: str | None,
    hardware: HardwareDescriptor,
    attempts: tuple[SearchAttemptRecord, ...],
    score: QueryFamilyScore | None = None,
    experiment_id: str | None = None,
    comparison_id: str | None = None,
    random_seed: int | None = None,
    run_id: UUID | None = None,
    started_at: datetime | None = None,
) -> QueryRunRecord:
    """Bind attempts and optional scores to a reviewed family and source versions."""
    if alignments.calibration_dataset_id != calibration.dataset_id:
        raise RunRecordError("source alignment belongs to another calibration")
    if alignments.snapshot_id != calibration.snapshot_id:
        raise RunRecordError("source alignment belongs to another snapshot")
    family = next((item for item in calibration.families if item.id == family_id), None)
    if family is None:
        raise RunRecordError(f"unknown calibration family: {family_id}")
    if query_id not in {query.id for query in family.queries}:
        raise RunRecordError("query_id does not belong to family_id")
    if any(attempt.filters != family.filters for attempt in attempts):
        raise RunRecordError("search attempts do not use the calibration filters")
    return QueryRunRecord(
        run_id=run_id or uuid4(),
        experiment_id=experiment_id,
        comparison_id=comparison_id,
        started_at=started_at or datetime.now(timezone.utc),
        calibration_dataset_id=calibration.dataset_id,
        calibration_sha256=calibration_sha256,
        split_policy_id=calibration.split_policy_id,
        family_id=family.id,
        query_id=query_id,
        split=family.split,
        snapshot_id=calibration.snapshot_id,
        source_alignment_id=alignments.alignment_id,
        source_alignment_sha256=source_alignment_sha256,
        source_matching_policy_id=alignments.policy_id,
        scoring_policy_id=(
            score.scoring_policy_id
            if score is not None
            else "evaluation-scoring-policy-v1"
        ),
        code_revision=code_revision,
        working_tree_dirty=working_tree_dirty,
        working_tree_diff_sha256=working_tree_diff_sha256,
        hardware=hardware,
        random_seed=random_seed,
        attempts=attempts,
        score=score,
    )


def sha256_file(path: str | Path) -> str:
    """Hash an exact benchmark or source-alignment file for run lineage."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_run_record(path: str | Path, record: QueryRunRecord) -> Path:
    """Atomically create raw JSON under the ignored local-reference run directory."""
    target = Path(path)
    if not target.is_absolute():
        target = Path.cwd() / target
    resolved_root = _RUN_ROOT.resolve()
    if not resolved_root.is_relative_to(_REPOSITORY_ROOT.resolve()):
        raise RunRecordError("raw run directory must remain inside the repository")
    resolved_target = target.resolve()
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise RunRecordError(
            f"raw run records must be stored below {resolved_root}"
        ) from exc
    if resolved_target.suffix != ".json":
        raise RunRecordError("run record files must use the .json suffix")
    _make_private_run_directory(resolved_root, resolved_target.parent)
    payload = _record_bytes(record)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{resolved_target.name}.",
        suffix=".tmp",
        dir=resolved_target.parent,
    )
    try:
        with os.fdopen(file_descriptor, "wb") as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        os.link(temporary_name, resolved_target)
        os.unlink(temporary_name)
        directory_descriptor = os.open(resolved_target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except FileExistsError as exc:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise RunRecordError("run record path already exists") from exc
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return resolved_target


def sanitized_run_summary(record: QueryRunRecord) -> dict[str, object]:
    """Return IDs, counts, timing, and metrics without result identities or text."""
    return {
        "schema_version": 1,
        "run_id": str(record.run_id),
        "raw_record_sha256": hashlib.sha256(_record_bytes(record)).hexdigest(),
        "experiment_id": record.experiment_id,
        "comparison_id": record.comparison_id,
        "calibration_dataset_id": record.calibration_dataset_id,
        "calibration_sha256": record.calibration_sha256,
        "split_policy_id": record.split_policy_id,
        "snapshot_id": str(record.snapshot_id),
        "source_alignment_id": record.source_alignment_id,
        "source_alignment_sha256": record.source_alignment_sha256,
        "source_matching_policy_id": record.source_matching_policy_id,
        "code_revision": record.code_revision,
        "working_tree_dirty": record.working_tree_dirty,
        "random_seed": record.random_seed,
        "split": record.split,
        "family_id": record.family_id,
        "query_id": record.query_id,
        "status": record.status,
        "scoring_policy_id": record.scoring_policy_id,
        "hardware": record.hardware.to_dict(),
        "attempts": [
            {
                "attempt_id": str(attempt.attempt_id),
                "operation": attempt.operation.value,
                "retrieval_profile_id": attempt.retrieval_profile_id,
                "effective_configuration_id": attempt.effective_configuration_id,
                "requested_mode": attempt.requested_mode.value,
                "effective_mode": (
                    attempt.effective_mode.value if attempt.effective_mode else None
                ),
                "status": attempt.status,
                "latency_ms": attempt.latency_ms,
                "latency_kind": attempt.latency_kind,
                "warning_count": attempt.warning_count,
                "truncated": attempt.truncated,
                "omitted_count": attempt.omitted_count,
                "failure_category": attempt.failure_category,
                "paper_result_count": len(attempt.paper_results),
                "evidence_result_count": len(attempt.evidence_results),
            }
            for attempt in record.attempts
        ],
        "score": _score_dict(record.score) if record.score is not None else None,
    }


def _evidence_result(hit: EvidenceHit) -> EvidenceResultRecord:
    return EvidenceResultRecord(
        rank=hit.rank,
        chunk_id=hit.chunk_id,
        source_evidence_ids=hit.source_evidence_ids,
        paper_id=hit.paper_id,
        document_id=hit.document_id,
        document_version=hit.document_version,
        document_version_kind=hit.document_version_kind,
        extraction_id=hit.extraction_id,
        chunking_configuration_id=hit.chunking_configuration_id,
        kind=hit.kind,
        source_location=hit.source_location,
        component_scores=hit.component_scores,
    )


def _paper_result(hit: PaperHit) -> PaperResultRecord:
    return PaperResultRecord(
        rank=hit.rank,
        paper_id=hit.paper_id,
        result_kind="paper",
        component_scores=hit.component_scores,
        supporting_evidence=tuple(
            _evidence_result(evidence) for evidence in hit.supporting_evidence
        ),
    )


def _metadata_result(hit: PaperMetadataHit) -> PaperResultRecord:
    return PaperResultRecord(
        rank=hit.rank,
        paper_id=hit.paper_id,
        result_kind="paper_metadata",
        component_scores=hit.component_scores,
    )


def _validate_component_scores(scores: ComponentScores) -> None:
    if not isinstance(scores, ComponentScores):
        raise ValueError("component_scores must be ComponentScores")
    for component in (scores.lexical, scores.dense, scores.fusion, scores.reranker):
        if component is not None and not isinstance(component, RankedComponent):
            raise ValueError("each component score must be a RankedComponent or null")


def _component_scores_dict(scores: ComponentScores) -> dict[str, object]:
    _validate_component_scores(scores)
    return {
        name: None
        if component is None
        else {"rank": component.rank, "score": component.score}
        for name, component in (
            ("lexical", scores.lexical),
            ("dense", scores.dense),
            ("fusion", scores.fusion),
            ("reranker", scores.reranker),
        )
    }


def _metric_dict(metric: MetricValue) -> dict[str, object]:
    return {
        "value": metric.value,
        "numerator": metric.numerator,
        "denominator": metric.denominator,
    }


def _ranking_dict(ranking: RankingMetrics) -> dict[str, object]:
    return {
        "ndcg_at_10": _metric_dict(ranking.ndcg_at_10),
        "direct_mrr_at_10": _metric_dict(ranking.direct_mrr_at_10),
        "judged_recall_at_20": _metric_dict(ranking.judged_recall_at_20),
        "judged_recall_at_50": _metric_dict(ranking.judged_recall_at_50),
        "judgment_coverage": _metric_dict(ranking.judgment_coverage),
    }


def _score_dict(score: QueryFamilyScore) -> dict[str, object]:

    profile = score.unsupported_profile
    return {
        "calibration_dataset_id": score.calibration_dataset_id,
        "snapshot_id": str(score.snapshot_id),
        "source_alignment_id": score.source_alignment_id,
        "source_matching_policy_id": score.source_matching_policy_id,
        "scoring_policy_id": score.scoring_policy_id,
        "family_id": score.family_id,
        "query_id": score.query_id,
        "split": score.split,
        "eligible_paper_count": score.eligible_paper_count,
        "empty_eligibility": score.empty_eligibility,
        "paper": _ranking_dict(score.paper),
        "evidence": _ranking_dict(score.evidence),
        "evidence_group_coverage": [
            {
                "cutoff": coverage.cutoff,
                "required_pieces": _metric_dict(coverage.required_pieces),
                "complete_groups": _metric_dict(coverage.complete_groups),
            }
            for coverage in score.evidence_group_coverage
        ],
        "unsupported_profile": (
            None
            if profile is None
            else {
                "paper_hits": _grade_counts_dict(profile.paper_hits),
                "evidence_hits": _grade_counts_dict(profile.evidence_hits),
            }
        ),
    }


def _grade_counts_dict(counts: HitGradeCounts) -> dict[str, int]:
    return {
        "returned": counts.returned,
        "judged": counts.judged,
        "unjudged": counts.unjudged,
        "label_0": counts.label_0,
        "label_1": counts.label_1,
        "label_2": counts.label_2,
    }


def _record_bytes(record: QueryRunRecord) -> bytes:
    return json.dumps(
        record.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _make_private_run_directory(root: Path, target: Path) -> None:
    """Create/chmod the dedicated raw-artifact directories for the current user."""
    relative_parts = target.relative_to(root).parts
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(mode=0o700, exist_ok=True)
    root.chmod(0o700)
    current = root
    for part in relative_parts:
        current = current / part
        current.mkdir(mode=0o700, exist_ok=True)
        current.chmod(0o700)
