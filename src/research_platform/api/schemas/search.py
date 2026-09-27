"""HTTP-boundary schemas for paper and evidence search."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_platform.ingestion.evidence import (
    EvidenceKind,
    EvidenceSourceSpan,
    SourceLocation,
)
from research_platform.ingestion.identity import DocumentVersionKind
from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    EvidenceHit,
    PaperHit,
    PaperMetadataHit,
    RetrievalMode,
    SearchFilters,
    SearchOperation,
    SearchRankingInterpretation,
    SearchRequest,
    SearchResponse,
    SearchResultStatus,
    TableCellEvidence,
    TableEvidenceContext,
    TableRowEvidence,
)

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, str_strip_whitespace=True, from_attributes=True
    )


class SearchFiltersModel(_StrictModel):
    """Optional filters with explicit range and choice validation."""

    year_from: int | None = Field(default=None, strict=True, ge=0)
    year_to: int | None = Field(default=None, strict=True, ge=0)
    paper_ids: tuple[str, ...] | None = Field(
        default=None,
        min_length=1,
        max_length=DEFAULT_SEARCH_LIMITS.max_filter_paper_ids,
    )
    evidence_kinds: tuple[EvidenceKind, ...] | None = Field(
        default=None, min_length=1, max_length=6
    )
    document_version_kinds: tuple[DocumentVersionKind, ...] | None = Field(
        default=None, min_length=1, max_length=4
    )

    @field_validator("paper_ids")
    @classmethod
    def validate_paper_ids(
        cls, values: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        if values is None:
            return None
        if len(set(values)) != len(values):
            raise ValueError("paper_ids must not contain duplicates")
        if any(
            not value.startswith("W") or not value[1:].isdigit() for value in values
        ):
            raise ValueError("paper_ids must be canonical OpenAlex work IDs")
        return values

    @model_validator(mode="after")
    def validate_ranges_and_choices(self) -> SearchFiltersModel:
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from must be less than or equal to year_to")
        if self.evidence_kinds is not None and len(set(self.evidence_kinds)) != len(
            self.evidence_kinds
        ):
            raise ValueError("evidence_kinds must not contain duplicates")
        if self.document_version_kinds is not None and len(
            set(self.document_version_kinds)
        ) != len(self.document_version_kinds):
            raise ValueError("document_version_kinds must not contain duplicates")
        return self

    def to_contract(self) -> SearchFilters:
        """Convert the HTTP model to the framework-independent filter contract."""
        return SearchFilters(
            year_from=self.year_from,
            year_to=self.year_to,
            paper_ids=self.paper_ids,
            evidence_kinds=self.evidence_kinds,
            document_version_kinds=self.document_version_kinds,
        )


class _SearchRequestModel(_StrictModel):
    query: str = Field(strict=True)
    snapshot_id: UUID
    retrieval_profile_id: str = Field(strict=True, pattern=_SHA256_PATTERN)
    mode: RetrievalMode
    filters: SearchFiltersModel = Field(default_factory=SearchFiltersModel)
    limit: int = Field(
        default=DEFAULT_SEARCH_LIMITS.default_result_limit,
        strict=True,
        ge=1,
        le=DEFAULT_SEARCH_LIMITS.max_result_limit,
    )

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must not be blank")
        if len(normalized) > DEFAULT_SEARCH_LIMITS.max_query_characters:
            raise ValueError("query exceeds the configured character limit")
        return normalized

    def _to_contract(self, operation: SearchOperation) -> SearchRequest:
        return SearchRequest(
            query=self.query,
            snapshot_id=self.snapshot_id,
            retrieval_profile_id=self.retrieval_profile_id,
            mode=self.mode,
            operation=operation,
            filters=self.filters.to_contract(),
            limit=self.limit,
        )


class PaperSearchRequest(_SearchRequestModel):
    """Request for one result per paper with its evidence contribution."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "query": "synthetic test: methods for document retrieval",
                    "snapshot_id": "4b11fab3-d4a5-4e7a-a58e-8654accf2c6c",
                    "retrieval_profile_id": "sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870",
                    "mode": "reranked",
                    "limit": 10,
                },
                {
                    "query": "synthetic test: papers with a publication year",
                    "snapshot_id": "4b11fab3-d4a5-4e7a-a58e-8654accf2c6c",
                    "retrieval_profile_id": "sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870",
                    "mode": "reranked",
                    "filters": {"year_from": 2099},
                    "limit": 10,
                },
            ]
        },
    )

    def to_contract(self) -> SearchRequest:
        return self._to_contract(SearchOperation.PAPER_SEARCH)


class EvidenceSearchRequest(_SearchRequestModel):
    """Request for ranked source-linked evidence units."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "query": "synthetic test: a prose passage about retrieval",
                    "snapshot_id": "4b11fab3-d4a5-4e7a-a58e-8654accf2c6c",
                    "retrieval_profile_id": "sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870",
                    "mode": "reranked",
                    "limit": 10,
                },
                {
                    "query": "synthetic test: values in a benchmark table",
                    "snapshot_id": "4b11fab3-d4a5-4e7a-a58e-8654accf2c6c",
                    "retrieval_profile_id": "sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870",
                    "mode": "reranked",
                    "filters": {"evidence_kinds": ["table", "table_row_group"]},
                    "limit": 10,
                },
            ]
        },
    )

    def to_contract(self) -> SearchRequest:
        return self._to_contract(SearchOperation.EVIDENCE_SEARCH)


class RankedComponentModel(_StrictModel):
    rank: int | None = Field(default=None, strict=True, ge=1)
    score: float | None = Field(default=None, allow_inf_nan=False)


class ComponentScoresModel(_StrictModel):
    lexical: RankedComponentModel | None = None
    dense: RankedComponentModel | None = None
    fusion: RankedComponentModel | None = None
    reranker: RankedComponentModel | None = None


class SourceLocationModel(_StrictModel):
    page_index_zero_based: int | None = Field(default=None, strict=True, ge=0)
    printed_page_label: str | None = None
    bounding_box: tuple[float, float, float, float] | None = None
    coordinate_system: str | None = None

    @model_validator(mode="after")
    def validate_source_location(self) -> SourceLocationModel:
        try:
            SourceLocation(
                page_index_zero_based=self.page_index_zero_based,
                printed_page_label=self.printed_page_label,
                bounding_box=self.bounding_box,
                coordinate_system=self.coordinate_system,
            )
        except ValueError as error:
            raise ValueError(str(error)) from None
        return self


class EvidenceSourceSpanModel(_StrictModel):
    section_ordinal: int = Field(strict=True, ge=0)
    start_offset: int = Field(strict=True, ge=0)
    end_offset: int = Field(strict=True, ge=1)
    chunk_start_offset: int = Field(strict=True, ge=0)
    chunk_end_offset: int = Field(strict=True, ge=1)
    heading_path: tuple[str, ...]
    source_location: SourceLocationModel

    @model_validator(mode="after")
    def validate_span(self) -> EvidenceSourceSpanModel:
        try:
            EvidenceSourceSpan(
                section_ordinal=self.section_ordinal,
                start_offset=self.start_offset,
                end_offset=self.end_offset,
                chunk_start_offset=self.chunk_start_offset,
                chunk_end_offset=self.chunk_end_offset,
                heading_path=self.heading_path,
                source_location=SourceLocation(
                    page_index_zero_based=self.source_location.page_index_zero_based,
                    printed_page_label=self.source_location.printed_page_label,
                    bounding_box=self.source_location.bounding_box,
                    coordinate_system=self.source_location.coordinate_system,
                ),
            )
        except ValueError as error:
            raise ValueError(str(error)) from None
        return self


class TableCellEvidenceModel(_StrictModel):
    row_index: int = Field(strict=True, ge=0)
    column_index: int = Field(strict=True, ge=0)
    value: str
    value_scope: Literal["cell", "segment"]
    row_header_references: tuple[tuple[int, int], ...] = ()
    column_header_references: tuple[tuple[int, int], ...] = ()
    row_headers: tuple[str, ...] = ()
    column_headers: tuple[str, ...] = ()
    token_start: int | None = Field(default=None, strict=True, ge=0)
    token_end_exclusive: int | None = Field(default=None, strict=True, ge=1)
    merged_range: tuple[int, int, int, int] | None = None

    @classmethod
    def from_contract(cls, cell: TableCellEvidence) -> TableCellEvidenceModel:
        return cls.model_validate(cell, from_attributes=True)


class TableRowEvidenceModel(_StrictModel):
    row_index: int = Field(strict=True, ge=0)
    cells: tuple[TableCellEvidenceModel, ...]

    @classmethod
    def from_contract(cls, row: TableRowEvidence) -> TableRowEvidenceModel:
        return cls.model_validate(row, from_attributes=True)


class TableEvidenceContextModel(_StrictModel):
    table_ordinal: int = Field(strict=True, ge=0)
    header_row_count: int = Field(strict=True, ge=0)
    caption: str | None
    units: str | None
    footnotes: tuple[str, ...]
    header_rows: tuple[TableRowEvidenceModel, ...]
    selected_rows: tuple[TableRowEvidenceModel, ...]
    selected_cells: tuple[TableCellEvidenceModel, ...]
    source_evidence_ids: tuple[str, ...]

    @classmethod
    def from_contract(cls, context: TableEvidenceContext) -> TableEvidenceContextModel:
        return cls.model_validate(context, from_attributes=True)


class EvidenceHitModel(_StrictModel):
    chunk_id: str
    source_evidence_ids: tuple[str, ...]
    paper_id: str
    document_id: UUID
    document_version: str
    document_version_kind: DocumentVersionKind
    extraction_id: UUID
    chunking_configuration_id: str | None
    kind: EvidenceKind
    source_location: SourceLocationModel
    source_spans: tuple[EvidenceSourceSpanModel, ...] = ()
    rank: int = Field(strict=True, ge=1)
    component_scores: ComponentScoresModel
    text: str
    table_context: TableEvidenceContextModel | None = None

    @classmethod
    def from_contract(cls, hit: EvidenceHit) -> EvidenceHitModel:
        return cls.model_validate(hit, from_attributes=True)


class PaperMetadataHitModel(_StrictModel):
    """Paper metadata result with no field capable of carrying evidence text."""

    paper_id: str
    title: str | None
    publication_year: int | None
    rank: int = Field(strict=True, ge=1)
    component_scores: ComponentScoresModel

    @classmethod
    def from_contract(cls, hit: PaperMetadataHit) -> PaperMetadataHitModel:
        return cls.model_validate(hit, from_attributes=True)


class PaperHitModel(_StrictModel):
    paper_id: str
    title: str | None
    publication_year: int | None
    rank: int = Field(strict=True, ge=1)
    component_scores: ComponentScoresModel
    supporting_evidence: tuple[EvidenceHitModel, ...] = Field(
        default=(), max_length=DEFAULT_SEARCH_LIMITS.max_per_paper_evidence_limit
    )
    metadata_rank: int | None = Field(default=None, strict=True, ge=1)
    evidence_rank: int | None = Field(default=None, strict=True, ge=1)

    @classmethod
    def from_contract(cls, hit: PaperHit) -> PaperHitModel:
        return cls.model_validate(hit, from_attributes=True)


class _SearchResponseModel(_StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    snapshot_id: UUID
    retrieval_profile_id: str = Field(pattern=_SHA256_PATTERN)
    effective_configuration_id: str = Field(pattern=_SHA256_PATTERN)
    requested_mode: RetrievalMode
    effective_mode: RetrievalMode
    eligible_count: int = Field(ge=0)
    result_status: SearchResultStatus
    ranking_interpretation: SearchRankingInterpretation
    warnings: tuple[str, ...] = ()
    truncated: bool
    omitted_count: int = Field(ge=0)


class PaperSearchResponse(_SearchResponseModel):
    hits: tuple[PaperHitModel, ...] = Field(
        max_length=DEFAULT_SEARCH_LIMITS.max_result_limit
    )

    @classmethod
    def from_contract(cls, response: SearchResponse[PaperHit]) -> PaperSearchResponse:
        return cls.model_validate(response, from_attributes=True)


class PaperMetadataResponse(_SearchResponseModel):
    hits: tuple[PaperMetadataHitModel, ...] = Field(
        max_length=DEFAULT_SEARCH_LIMITS.max_result_limit
    )

    @classmethod
    def from_contract(
        cls, response: SearchResponse[PaperMetadataHit]
    ) -> PaperMetadataResponse:
        return cls.model_validate(response, from_attributes=True)


class EvidenceSearchResponse(_SearchResponseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "request_id": "request-synthetic-001",
                    "snapshot_id": "4b11fab3-d4a5-4e7a-a58e-8654accf2c6c",
                    "retrieval_profile_id": "sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870",
                    "effective_configuration_id": "sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870",
                    "requested_mode": "reranked",
                    "effective_mode": "hybrid",
                    "eligible_count": 42,
                    "result_status": "ranked_candidates",
                    "ranking_interpretation": "ranking_only",
                    "warnings": [
                        "reranking failed; unchanged hybrid order was returned"
                    ],
                    "truncated": False,
                    "omitted_count": 0,
                    "hits": [],
                },
                {
                    "request_id": "request-synthetic-002",
                    "snapshot_id": "4b11fab3-d4a5-4e7a-a58e-8654accf2c6c",
                    "retrieval_profile_id": "sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870",
                    "effective_configuration_id": "sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870",
                    "requested_mode": "reranked",
                    "effective_mode": "reranked",
                    "eligible_count": 0,
                    "result_status": "no_eligible_records",
                    "ranking_interpretation": "ranking_only",
                    "warnings": [],
                    "truncated": False,
                    "omitted_count": 0,
                    "hits": [],
                },
            ]
        },
    )

    hits: tuple[EvidenceHitModel, ...] = Field(
        max_length=DEFAULT_SEARCH_LIMITS.max_result_limit
    )

    @classmethod
    def from_contract(
        cls, response: SearchResponse[EvidenceHit]
    ) -> EvidenceSearchResponse:
        return cls.model_validate(response, from_attributes=True)
