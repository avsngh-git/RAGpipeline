"""Framework-independent contracts for bounded paper and evidence search."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Generic, Literal, TypeVar
from uuid import UUID

from research_platform.ingestion.evidence import (
    EvidenceKind,
    EvidenceSourceSpan,
    SourceLocation,
)
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


class SearchResultStatus(str, Enum):
    """Why a bounded search response contains or lacks ranked candidates."""

    RANKED_CANDIDATES = "ranked_candidates"
    NO_ELIGIBLE_RECORDS = "no_eligible_records"
    NO_CANDIDATES_RETURNED = "no_candidates_returned"


class SearchRankingInterpretation(str, Enum):
    """Interpretation guaranteed by retrieval before relevance calibration."""

    RANKING_ONLY = "ranking_only"


def _search_result_status(
    eligible_count: int, returned_count: int
) -> SearchResultStatus:
    if eligible_count == 0:
        return SearchResultStatus.NO_ELIGIBLE_RECORDS
    if returned_count == 0:
        return SearchResultStatus.NO_CANDIDATES_RETURNED
    return SearchResultStatus.RANKED_CANDIDATES


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
    default_evidence_context_characters: int = 12_000
    max_evidence_context_characters: int = 24_000
    default_evidence_context_tokens: int = 4_000
    max_evidence_context_tokens: int = 8_000
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
            "default_evidence_context_characters",
            "max_evidence_context_characters",
            "default_evidence_context_tokens",
            "max_evidence_context_tokens",
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
            self.default_evidence_context_characters
            > self.max_evidence_context_characters
        ):
            raise ValueError(
                "default_evidence_context_characters cannot exceed its maximum"
            )
        if self.default_evidence_context_tokens > self.max_evidence_context_tokens:
            raise ValueError(
                "default_evidence_context_tokens cannot exceed its maximum"
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


TableCoordinate = tuple[int, int]


@dataclass(frozen=True)
class TableCellEvidence:
    """One selected or header cell with resolved labels and exact source coordinates."""

    row_index: int
    column_index: int
    value: str
    value_scope: Literal["cell", "segment"]
    row_header_references: tuple[TableCoordinate, ...] = ()
    column_header_references: tuple[TableCoordinate, ...] = ()
    row_headers: tuple[str, ...] = ()
    column_headers: tuple[str, ...] = ()
    token_start: int | None = None
    token_end_exclusive: int | None = None
    merged_range: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        for name in ("row_index", "column_index"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.value, str):
            raise ValueError("table cell value must be a string")
        if self.value_scope not in {"cell", "segment"}:
            raise ValueError("table cell value_scope must be cell or segment")
        _validate_table_references(self.row_header_references, "row_header_references")
        _validate_table_references(
            self.column_header_references, "column_header_references"
        )
        for name in ("row_headers", "column_headers"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) for value in values
            ):
                raise ValueError(f"{name} must contain strings")
        if self.value_scope == "cell":
            if self.token_start is not None or self.token_end_exclusive is not None:
                raise ValueError("full-cell values must not include a token range")
        elif (
            isinstance(self.token_start, bool)
            or not isinstance(self.token_start, int)
            or self.token_start < 0
            or isinstance(self.token_end_exclusive, bool)
            or not isinstance(self.token_end_exclusive, int)
            or self.token_end_exclusive <= self.token_start
        ):
            raise ValueError("cell segments require a valid half-open token range")
        if self.merged_range is not None:
            if (
                not isinstance(self.merged_range, tuple)
                or len(self.merged_range) != 4
                or any(
                    isinstance(value, bool) or not isinstance(value, int)
                    for value in self.merged_range
                )
            ):
                raise ValueError("merged_range must contain four integer coordinates")
            row_start, column_start, row_end, column_end = self.merged_range
            if (
                row_start < 0
                or column_start < 0
                or row_end < self.row_index
                or column_end < self.column_index
                or not row_start <= self.row_index <= row_end
                or not column_start <= self.column_index <= column_end
            ):
                raise ValueError("merged_range must contain the cell coordinates")


@dataclass(frozen=True)
class TableRowEvidence:
    """A table row represented by explicit source cells without fabricated blanks."""

    row_index: int
    cells: tuple[TableCellEvidence, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.row_index, bool)
            or not isinstance(self.row_index, int)
            or self.row_index < 0
        ):
            raise ValueError("row_index must be a non-negative integer")
        if not isinstance(self.cells, tuple) or any(
            not isinstance(cell, TableCellEvidence) for cell in self.cells
        ):
            raise ValueError("cells must contain TableCellEvidence values")
        if any(
            cell.row_index != self.row_index or cell.value_scope != "cell"
            for cell in self.cells
        ):
            raise ValueError("table row cells must be full cells in their source row")
        columns = tuple(cell.column_index for cell in self.cells)
        if len(set(columns)) != len(columns):
            raise ValueError("table row must not repeat cell columns")


@dataclass(frozen=True)
class TableEvidenceContext:
    """Structured table headers and selected body cells for one evidence hit."""

    table_ordinal: int
    header_row_count: int
    caption: str | None
    units: str | None
    footnotes: tuple[str, ...]
    header_rows: tuple[TableRowEvidence, ...]
    selected_rows: tuple[TableRowEvidence, ...]
    selected_cells: tuple[TableCellEvidence, ...]
    source_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.table_ordinal, bool)
            or not isinstance(self.table_ordinal, int)
            or self.table_ordinal < 0
        ):
            raise ValueError("table_ordinal must be a non-negative integer")
        if (
            isinstance(self.header_row_count, bool)
            or not isinstance(self.header_row_count, int)
            or self.header_row_count < 0
        ):
            raise ValueError("header_row_count must be a non-negative integer")
        for name in ("caption", "units"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be a string or null")
        if not isinstance(self.footnotes, tuple) or any(
            not isinstance(note, str) for note in self.footnotes
        ):
            raise ValueError("footnotes must contain strings")
        for name in ("header_rows", "selected_rows"):
            rows = getattr(self, name)
            if not isinstance(rows, tuple) or any(
                not isinstance(row, TableRowEvidence) for row in rows
            ):
                raise ValueError(f"{name} must contain TableRowEvidence values")
            indices = tuple(row.row_index for row in rows)
            if tuple(sorted(set(indices))) != indices:
                raise ValueError(f"{name} must have unique rows in source order")
        header_indices = tuple(row.row_index for row in self.header_rows)
        if tuple(sorted(set(header_indices))) != header_indices or any(
            row_index >= self.header_row_count for row_index in header_indices
        ):
            raise ValueError("header rows must be unique rows within the table header")
        header_index_set = set(header_indices)
        if any(
            row.row_index in header_index_set or row.row_index < self.header_row_count
            for row in self.selected_rows
        ):
            raise ValueError("selected body rows cannot repeat header rows")
        if any(cell.row_index < self.header_row_count for cell in self.selected_cells):
            raise ValueError("selected cell segments cannot refer to header rows")
        if not isinstance(self.selected_cells, tuple) or any(
            not isinstance(cell, TableCellEvidence) or cell.value_scope != "segment"
            for cell in self.selected_cells
        ):
            raise ValueError("selected_cells must contain segmented table cells")
        if not self.selected_rows and not self.selected_cells:
            raise ValueError("table context must contain selected body rows or cells")
        if (
            not isinstance(self.source_evidence_ids, tuple)
            or not self.source_evidence_ids
        ):
            raise ValueError("source_evidence_ids must be a non-empty tuple")
        if any(
            not isinstance(item, str) or not item.strip()
            for item in self.source_evidence_ids
        ):
            raise ValueError("source_evidence_ids must contain non-empty IDs")


def _validate_table_references(
    references: tuple[TableCoordinate, ...], name: str
) -> None:
    if not isinstance(references, tuple) or any(
        not isinstance(reference, tuple)
        or len(reference) != 2
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in reference
        )
        for reference in references
    ):
        raise ValueError(f"{name} must contain non-negative table coordinates")


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
    table_context: TableEvidenceContext | None = None
    source_spans: tuple[EvidenceSourceSpan, ...] = ()

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
        if not isinstance(self.source_spans, tuple) or any(
            not isinstance(span, EvidenceSourceSpan) for span in self.source_spans
        ):
            raise ValueError("source_spans must contain EvidenceSourceSpan values")
        previous_chunk_end = 0
        for span in self.source_spans:
            if span.chunk_end_offset > len(self.text):
                raise ValueError("source spans must fit within the evidence text")
            if span.chunk_start_offset < previous_chunk_end:
                raise ValueError(
                    "source spans must not overlap or change reading order"
                )
            previous_chunk_end = span.chunk_end_offset
        if self.table_context is not None:
            if not isinstance(self.table_context, TableEvidenceContext):
                raise ValueError("table_context must be TableEvidenceContext or null")
            if self.kind not in {"table", "table_row_group"}:
                raise ValueError("only table hits may carry table_context")
            if self.table_context.source_evidence_ids != self.source_evidence_ids:
                raise ValueError("table context source IDs must match the evidence hit")


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
    """Paper result with fused and branch-specific paper ranks.

    Evidence passage ranks remain on ``supporting_evidence``; ``evidence_rank``
    is the paper's rank in the evidence-derived paper candidate stream.
    """

    paper_id: str
    title: str | None
    publication_year: int | None
    rank: int
    component_scores: ComponentScores
    supporting_evidence: tuple[EvidenceHit, ...] = ()
    metadata_rank: int | None = None
    evidence_rank: int | None = None

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
        for name in ("metadata_rank", "evidence_rank"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{name} must be a positive integer or null")
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
    eligible_count: int
    warnings: tuple[str, ...] = ()
    truncated: bool = False
    omitted_count: int = 0
    result_status: SearchResultStatus = field(init=False)
    ranking_interpretation: SearchRankingInterpretation = field(
        default=SearchRankingInterpretation.RANKING_ONLY, init=False
    )

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
        if (
            isinstance(self.eligible_count, bool)
            or not isinstance(self.eligible_count, int)
            or self.eligible_count < 0
        ):
            raise ValueError("eligible_count must be a non-negative integer")
        if len(self.hits) > self.eligible_count:
            raise ValueError("returned hits cannot exceed the eligible record count")
        object.__setattr__(
            self,
            "result_status",
            _search_result_status(self.eligible_count, len(self.hits)),
        )
        if self.ranking_interpretation is not SearchRankingInterpretation.RANKING_ONLY:
            raise ValueError("search responses provide ranking only")
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
