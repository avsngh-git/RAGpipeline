"""Typed paper and citation response models."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from research_platform.search.paper_graph import (
    CitationDirection,
    CitationEndpointStatus,
    CitationGraphPage,
)
from research_platform.search.paper_reads import (
    MetadataAvailability,
    PaperReadStatus,
    SnapshotPaperRead,
)


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class PaperReadResponse(_StrictResponse):
    """Paper metadata/provenance without an abstract or source passage field."""

    snapshot_id: UUID
    paper_id: str = Field(pattern=r"^W[0-9]+$")
    status: PaperReadStatus
    title: str | None
    publication_year: int | None
    metadata_availability: MetadataAvailability
    document_id: UUID | None
    document_version: str | None
    document_version_kind: Literal["published", "preprint", "other", "unknown"] | None

    @classmethod
    def from_contract(cls, value: SnapshotPaperRead) -> PaperReadResponse:
        return cls.model_validate(value, from_attributes=True)


class CitationEndpointResponse(_StrictResponse):
    """One resolved, outside-snapshot, or unresolved graph endpoint."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "status": "unresolved",
                    "paper_id": None,
                    "title": None,
                    "publication_year": None,
                    "external_namespace": "doi",
                    "external_identifier": "10.5555/example.1",
                }
            ]
        },
    )
    status: CitationEndpointStatus
    paper_id: str | None
    title: str | None
    publication_year: int | None
    external_namespace: str | None
    external_identifier: str | None


class CitationEdgeResponse(_StrictResponse):
    endpoint: CitationEndpointResponse
    source: str


class CitationGraphResponse(_StrictResponse):
    """One bounded page of locally stored citation relationships."""

    snapshot_id: UUID
    paper_id: str = Field(pattern=r"^W[0-9]+$")
    direction: CitationDirection
    source_status: PaperReadStatus
    limit: int = Field(ge=1, le=100)
    edges: tuple[CitationEdgeResponse, ...]
    has_more: bool
    next_cursor: str | None
    coverage_note: str

    @classmethod
    def from_contract(
        cls, value: CitationGraphPage, *, next_cursor: str | None
    ) -> CitationGraphResponse:
        return cls(
            snapshot_id=value.snapshot_id,
            paper_id=value.paper_id,
            direction=value.direction,
            source_status=value.source_status,
            limit=value.limit,
            edges=tuple(
                CitationEdgeResponse(
                    endpoint=CitationEndpointResponse.model_validate(
                        edge.endpoint, from_attributes=True
                    ),
                    source=edge.source,
                )
                for edge in value.edges
            ),
            has_more=value.has_more,
            next_cursor=next_cursor,
            coverage_note=value.coverage_note,
        )
