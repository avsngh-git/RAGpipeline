"""Framework-independent contracts for bounded paper and evidence search."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Generic, TypeVar
from uuid import UUID

from research_platform.ingestion.evidence import EvidenceKind, SourceLocation
from research_platform.ingestion.identity import DocumentVersionKind, is_valid_paper_id

_SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


class RetrievalMode(str, Enum):
    """The retrieval stages requested for one search."""

    LEXICAL = "lexical"
    DENSE = "dense"
    HYBRID = "hybrid"
    RERANKED = "reranked"


class SearchOperation(str, Enum):
    """Search surface used when deciding whether a filter is applicable."""

    PAPER_SEARCH = "paper_search"
    EVIDENCE_SEARCH = "evidence_search"
    PAPER_METADATA = "paper_metadata"


@dataclass(frozen=True)
class SearchLimits:
    """Provisional, serializable work bounds for local search."""

    max_query_characters: int = 2_000
    default_result_limit: int = 10
    max_result_limit: int = 50
    default_candidate_limit: int = 50
    max_candidate_limit: int = 200
    default_per_paper_evidence_limit: int = 3
    max_per_paper_evidence_limit: int = 5
    max_filter_paper_ids: int = 100
    request_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        for name in (
            "max_query_characters",
            "default_result_limit",
            "max_result_limit",
            "default_candidate_limit",
            "max_candidate_limit",
            "default_per_paper_evidence_limit",
            "max_per_paper_evidence_limit",
            "max_filter_paper_ids",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.default_result_limit > self.max_result_limit:
            raise ValueError("default_result_limit cannot exceed max_result_limit")
        if self.default_candidate_limit > self.max_candidate_limit:
            raise ValueError(
                "default_candidate_limit cannot exceed max_candidate_limit"
            )
        if self.default_per_paper_evidence_limit > self.max_per_paper_evidence_limit:
            raise ValueError(
                "default_per_paper_evidence_limit cannot exceed its maximum"
            )
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, (int, float))
            or not math.isfinite(self.request_timeout_seconds)
            or self.request_timeout_seconds <= 0
        ):
            raise ValueError("request_timeout_seconds must be finite and positive")

    def to_dict(self) -> dict[str, object]:
        """Return the effective bounds in a JSON-serializable form."""
        return asdict(self)


DEFAULT_SEARCH_LIMITS = SearchLimits()


@dataclass(frozen=True)
class SearchFilters:
    """Typed filters applied before lexical or dense candidate limits."""

    year_from: int | None = None
    year_to: int | None = None
    paper_ids: tuple[str, ...] | None = None
    evidence_kinds: tuple[EvidenceKind, ...] | None = None
    document_version_kinds: tuple[DocumentVersionKind, ...] | None = None

    def __post_init__(self) -> None:
        for name in ("year_from", "year_to"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from must be less than or equal to year_to")
        if self.paper_ids is not None:
            if not isinstance(self.paper_ids, tuple) or not self.paper_ids:
                raise ValueError("paper_ids must be a non-empty tuple when provided")
            if len(self.paper_ids) > DEFAULT_SEARCH_LIMITS.max_filter_paper_ids:
                raise ValueError("paper_ids exceeds the configured maximum")
            if len(set(self.paper_ids)) != len(self.paper_ids):
                raise ValueError("paper_ids must not contain duplicates")
            if any(not is_valid_paper_id(paper_id) for paper_id in self.paper_ids):
                raise ValueError("paper_ids must be canonical OpenAlex work IDs")
        if self.evidence_kinds is not None:
            allowed = {
                "text",
                "table",
                "table_row_group",
                "caption",
                "figure",
                "equation",
            }
            if (
                not isinstance(self.evidence_kinds, tuple)
                or not self.evidence_kinds
                or any(kind not in allowed for kind in self.evidence_kinds)
            ):
                raise ValueError("evidence_kinds contains an unsupported value")
            if len(set(self.evidence_kinds)) != len(self.evidence_kinds):
                raise ValueError("evidence_kinds must not contain duplicates")
        if self.document_version_kinds is not None:
            allowed_versions = {"published", "preprint", "other", "unknown"}
            if (
                not isinstance(self.document_version_kinds, tuple)
                or not self.document_version_kinds
                or any(
                    kind not in allowed_versions for kind in self.document_version_kinds
                )
            ):
                raise ValueError("document_version_kinds contains an unsupported value")
            if len(set(self.document_version_kinds)) != len(
                self.document_version_kinds
            ):
                raise ValueError("document_version_kinds must not contain duplicates")

    def validate_for(self, operation: SearchOperation) -> None:
        """Reject evidence-only filters on paper metadata operations."""
        if (
            operation is SearchOperation.PAPER_METADATA
            and self.evidence_kinds is not None
        ):
            raise ValueError("evidence_kinds are not supported for paper metadata")

    def to_dict(self) -> dict[str, object]:
        """Return the selected filter values in a JSON-serializable form."""
        return {
            "year_from": self.year_from,
            "year_to": self.year_to,
            "paper_ids": list(self.paper_ids) if self.paper_ids is not None else None,
            "evidence_kinds": (
                list(self.evidence_kinds) if self.evidence_kinds is not None else None
            ),
            "document_version_kinds": (
                list(self.document_version_kinds)
                if self.document_version_kinds is not None
                else None
            ),
        }


def matches_filters(
    filters: SearchFilters,
    *,
    operation: SearchOperation,
    paper_id: str | None,
    publication_year: int | None,
    evidence_kind: EvidenceKind | None = None,
    document_version_kind: DocumentVersionKind | None = None,
) -> bool:
    """Apply AND across fields, OR within fields, failing closed on missing metadata."""
    filters.validate_for(operation)
    if filters.paper_ids is not None and paper_id not in filters.paper_ids:
        return False
    if filters.year_from is not None and (
        publication_year is None or publication_year < filters.year_from
    ):
        return False
    if filters.year_to is not None and (
        publication_year is None or publication_year > filters.year_to
    ):
        return False
    if filters.evidence_kinds is not None and (
        evidence_kind is None or evidence_kind not in filters.evidence_kinds
    ):
        return False
    if filters.document_version_kinds is not None and (
        document_version_kind is None
        or document_version_kind not in filters.document_version_kinds
    ):
        return False
    return True


@dataclass(frozen=True)
class SearchRequest:
    """Validated search input after conversion from the HTTP boundary model."""

    query: str
    snapshot_id: UUID
    retrieval_profile_id: str
    mode: RetrievalMode
    operation: SearchOperation
    filters: SearchFilters = SearchFilters()
    limit: int = DEFAULT_SEARCH_LIMITS.default_result_limit

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must not be blank")
        normalized_query = self.query.strip()
        if len(normalized_query) > DEFAULT_SEARCH_LIMITS.max_query_characters:
            raise ValueError("query exceeds the configured character limit")
        object.__setattr__(self, "query", normalized_query)
        if not isinstance(self.snapshot_id, UUID):
            raise ValueError("snapshot_id must be a UUID")
        if not isinstance(self.retrieval_profile_id, str) or not _SHA256_ID.fullmatch(
            self.retrieval_profile_id
        ):
            raise ValueError("retrieval_profile_id must be a SHA-256 identity")
        if not isinstance(self.mode, RetrievalMode):
            raise ValueError("mode must be a supported retrieval mode")
        if not isinstance(self.operation, SearchOperation):
            raise ValueError("operation must be a supported search operation")
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= DEFAULT_SEARCH_LIMITS.max_result_limit
        ):
            raise ValueError("limit is outside the configured result bounds")
        if not isinstance(self.filters, SearchFilters):
            raise ValueError("filters must be SearchFilters")
        self.filters.validate_for(self.operation)


@dataclass(frozen=True)
class RankedComponent:
    """Raw rank and score from one search component; score is not a probability."""

    rank: int | None = None
    score: float | None = None

    def __post_init__(self) -> None:
        if self.rank is not None and (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 1
        ):
            raise ValueError("rank must be a positive integer or null")
        if self.score is not None and (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not math.isfinite(self.score)
        ):
            raise ValueError("score must be finite or null")


@dataclass(frozen=True)
class ComponentScores:
    """Component rankings retained through fusion and optional reranking."""

    lexical: RankedComponent | None = None
    dense: RankedComponent | None = None
    fusion: RankedComponent | None = None
    reranker: RankedComponent | None = None


@dataclass(frozen=True)
class EvidenceHit:
    """A ranked chunk with its immutable source and chunk-version provenance."""

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
    rank: int
    component_scores: ComponentScores
    text: str

    def __post_init__(self) -> None:
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
        if (
            not isinstance(self.document_version, str)
            or not self.document_version.strip()
        ):
            raise ValueError("document_version must be non-empty")
        if self.chunking_configuration_id is not None and not _SHA256_ID.fullmatch(
            self.chunking_configuration_id
        ):
            raise ValueError(
                "chunking_configuration_id must be a SHA-256 identity or null"
            )
        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 1
        ):
            raise ValueError("rank must be a positive integer")
        if not isinstance(self.component_scores, ComponentScores):
            raise ValueError("component_scores must be ComponentScores")
        if not isinstance(self.text, str):
            raise ValueError("text must be a string")


@dataclass(frozen=True)
class PaperMetadataHit:
    """A paper-level result that intentionally carries no evidence text."""

    paper_id: str
    title: str | None
    publication_year: int | None
    rank: int
    component_scores: ComponentScores

    def __post_init__(self) -> None:
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if self.title is not None and not isinstance(self.title, str):
            raise ValueError("title must be a string or null")
        if self.publication_year is not None and (
            isinstance(self.publication_year, bool)
            or not isinstance(self.publication_year, int)
            or self.publication_year < 0
        ):
            raise ValueError("publication_year must be non-negative or null")
        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 1
        ):
            raise ValueError("rank must be a positive integer")
        if not isinstance(self.component_scores, ComponentScores):
            raise ValueError("component_scores must be ComponentScores")


@dataclass(frozen=True)
class PaperHit:
    """One paper-level result with separately retained evidence contributions."""

    paper_id: str
    title: str | None
    publication_year: int | None
    rank: int
    component_scores: ComponentScores
    supporting_evidence: tuple[EvidenceHit, ...] = ()

    def __post_init__(self) -> None:
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if self.title is not None and not isinstance(self.title, str):
            raise ValueError("title must be a string or null")
        if self.publication_year is not None and (
            isinstance(self.publication_year, bool)
            or not isinstance(self.publication_year, int)
            or self.publication_year < 0
        ):
            raise ValueError("publication_year must be non-negative or null")
        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 1
        ):
            raise ValueError("rank must be a positive integer")
        if not isinstance(self.component_scores, ComponentScores):
            raise ValueError("component_scores must be ComponentScores")
        if any(not isinstance(hit, EvidenceHit) for hit in self.supporting_evidence):
            raise ValueError("supporting_evidence must contain EvidenceHit values")
        if any(hit.paper_id != self.paper_id for hit in self.supporting_evidence):
            raise ValueError("supporting evidence must belong to this paper")


HitT = TypeVar("HitT", PaperHit, EvidenceHit, PaperMetadataHit)


@dataclass(frozen=True)
class SearchResponse(Generic[HitT]):
    """Bounded response metadata shared by paper and evidence searches."""

    request_id: str
    snapshot_id: UUID
    retrieval_profile_id: str
    effective_configuration_id: str
    requested_mode: RetrievalMode
    effective_mode: RetrievalMode
    hits: tuple[HitT, ...]
    warnings: tuple[str, ...] = ()
    truncated: bool = False
    omitted_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not 1 <= len(self.request_id) <= 128:
            raise ValueError("request_id must contain 1–128 characters")
        if not isinstance(self.snapshot_id, UUID):
            raise ValueError("snapshot_id must be a UUID")
        for name in ("retrieval_profile_id", "effective_configuration_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256_ID.fullmatch(value):
                raise ValueError(f"{name} must be a SHA-256 identity")
        if not isinstance(self.requested_mode, RetrievalMode) or not isinstance(
            self.effective_mode, RetrievalMode
        ):
            raise ValueError("requested_mode and effective_mode must be supported")
        if not isinstance(self.hits, tuple):
            raise ValueError("hits must be a tuple")
        if not isinstance(self.warnings, tuple) or any(
            not isinstance(warning, str) or not warning.strip()
            for warning in self.warnings
        ):
            raise ValueError("warnings must be non-empty strings")
        if (
            isinstance(self.omitted_count, bool)
            or not isinstance(self.omitted_count, int)
            or self.omitted_count < 0
        ):
            raise ValueError("omitted_count must be a non-negative integer")
