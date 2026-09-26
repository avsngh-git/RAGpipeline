"""Bounded, snapshot-aware reads for public paper identities."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.identity import (
    DocumentVersionKind,
    is_valid_paper_id,
)
from research_platform.ingestion.openalex import abstract_from_openalex_metadata


class PaperReadStatus(str, Enum):
    """Whether a public paper ID resolves within the requested snapshot."""

    IN_SNAPSHOT = "in_snapshot"
    OUTSIDE_SNAPSHOT = "outside_snapshot"
    UNKNOWN = "unknown"


class SnapshotNotFound(ValueError):
    """The requested snapshot does not exist."""


class PaperIdentityConflict(RuntimeError):
    """A public OpenAlex ID resolves to multiple local paper records."""


@dataclass(frozen=True)
class MetadataAvailability:
    """Presence of the metadata fields used by paper-level retrieval."""

    title: bool
    abstract: bool
    publication_year: bool

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, bool)
            for value in (self.title, self.abstract, self.publication_year)
        ):
            raise ValueError("metadata availability values must be booleans")


@dataclass(frozen=True)
class SnapshotPaperRead:
    """Metadata and selected document provenance without evidence text."""

    paper_id: str
    snapshot_id: UUID
    status: PaperReadStatus
    title: str | None
    publication_year: int | None
    metadata_availability: MetadataAvailability
    document_id: UUID | None = None
    document_version: str | None = None
    document_version_kind: DocumentVersionKind | None = None

    def __post_init__(self) -> None:
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if not isinstance(self.snapshot_id, UUID):
            raise ValueError("snapshot_id must be a UUID")
        if not isinstance(self.status, PaperReadStatus):
            raise ValueError("status must be a PaperReadStatus")
        if not isinstance(self.metadata_availability, MetadataAvailability):
            raise ValueError("metadata_availability must be MetadataAvailability")
        if self.title is not None and not isinstance(self.title, str):
            raise ValueError("title must be text or null")
        if self.publication_year is not None and (
            isinstance(self.publication_year, bool)
            or not isinstance(self.publication_year, int)
            or self.publication_year < 0
        ):
            raise ValueError("publication_year must be non-negative or null")
        if self.status is PaperReadStatus.IN_SNAPSHOT:
            if (
                not isinstance(self.document_id, UUID)
                or not isinstance(self.document_version, str)
                or not self.document_version.strip()
                or self.document_version_kind
                not in ("published", "preprint", "other", "unknown")
            ):
                raise ValueError(
                    "in-snapshot paper reads require selected version data"
                )
        elif any(
            value is not None
            for value in (
                self.document_id,
                self.document_version,
                self.document_version_kind,
            )
        ):
            raise ValueError("papers outside the snapshot have no selected version")
        if self.status is PaperReadStatus.UNKNOWN and any(
            (
                self.title is not None,
                self.publication_year is not None,
                self.metadata_availability.title,
                self.metadata_availability.abstract,
                self.metadata_availability.publication_year,
            )
        ):
            raise ValueError("unknown papers cannot carry metadata")


_READ_PAPER_SQL = """
WITH candidate_paper_ids AS (
    SELECT paper.id AS paper_id
    FROM papers AS paper
    WHERE paper.openalex_id = $2
    UNION
    SELECT identifier.paper_id
    FROM paper_identifiers AS identifier
    WHERE identifier.namespace = 'openalex'
      AND identifier.normalized_identifier = $2
),
bounded_candidates AS (
    SELECT paper_id
    FROM candidate_paper_ids
    ORDER BY paper_id
    LIMIT 2
),
requested_snapshot AS (
    SELECT $1::uuid AS snapshot_id
)
SELECT EXISTS (
           SELECT 1 FROM snapshots AS snapshot
           WHERE snapshot.id = requested_snapshot.snapshot_id
       ) AS snapshot_exists,
       (SELECT count(*) FROM candidate_paper_ids) AS resolved_count,
       paper.id AS local_paper_id,
       paper.title,
       paper.publication_year,
       paper.metadata -> 'abstract_inverted_index' AS abstract_inverted_index,
       item.paper_id AS snapshot_paper_id,
       item.document_id,
       document.version AS document_version,
       document.version_kind AS document_version_kind
FROM requested_snapshot
LEFT JOIN bounded_candidates AS candidate ON TRUE
LEFT JOIN papers AS paper ON paper.id = candidate.paper_id
LEFT JOIN snapshot_items AS item
  ON item.snapshot_id = requested_snapshot.snapshot_id
 AND item.paper_id = candidate.paper_id
LEFT JOIN documents AS document
  ON document.id = item.document_id
 AND document.paper_id = item.paper_id
"""


class SnapshotPaperReader:
    """Read one canonical public paper ID using a single bounded SQL query."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def read_paper(self, snapshot_id: UUID, paper_id: str) -> SnapshotPaperRead:
        """Resolve a paper and its selected version without querying evidence text."""
        if not isinstance(snapshot_id, UUID):
            raise ValueError("snapshot_id must be a UUID")
        if not is_valid_paper_id(paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")

        async with self._pool.acquire() as connection:
            rows = await connection.fetch(_READ_PAPER_SQL, snapshot_id, paper_id)
        if not rows:
            raise RuntimeError("paper read query returned no snapshot row")

        row = rows[0]
        if not row["snapshot_exists"]:
            raise SnapshotNotFound("snapshot does not exist")
        resolved_count = row["resolved_count"]
        if resolved_count > 1:
            raise PaperIdentityConflict(
                "public paper ID resolves to multiple local paper records"
            )
        if resolved_count == 0:
            return SnapshotPaperRead(
                paper_id=paper_id,
                snapshot_id=snapshot_id,
                status=PaperReadStatus.UNKNOWN,
                title=None,
                publication_year=None,
                metadata_availability=MetadataAvailability(
                    title=False, abstract=False, publication_year=False
                ),
            )
        if len(rows) != 1 or row["local_paper_id"] is None:
            raise RuntimeError("resolved paper identity did not return one paper row")

        title_value = row["title"]
        title = (
            title_value
            if isinstance(title_value, str) and title_value.strip()
            else None
        )
        publication_year = row["publication_year"]
        abstract_index = _metadata_object(row["abstract_inverted_index"])
        abstract = abstract_from_openalex_metadata(
            {"abstract_inverted_index": abstract_index}
        )
        availability = MetadataAvailability(
            title=title is not None,
            abstract=abstract is not None and bool(abstract.strip()),
            publication_year=publication_year is not None,
        )

        if row["snapshot_paper_id"] is None:
            return SnapshotPaperRead(
                paper_id=paper_id,
                snapshot_id=snapshot_id,
                status=PaperReadStatus.OUTSIDE_SNAPSHOT,
                title=title,
                publication_year=publication_year,
                metadata_availability=availability,
            )

        document_id = row["document_id"]
        document_version = row["document_version"]
        document_version_kind = row["document_version_kind"]
        if (
            not isinstance(document_id, UUID)
            or not isinstance(document_version, str)
            or document_version_kind
            not in ("published", "preprint", "other", "unknown")
        ):
            raise RuntimeError("snapshot member has incomplete document provenance")
        return SnapshotPaperRead(
            paper_id=paper_id,
            snapshot_id=snapshot_id,
            status=PaperReadStatus.IN_SNAPSHOT,
            title=title,
            publication_year=publication_year,
            metadata_availability=availability,
            document_id=document_id,
            document_version=document_version,
            document_version_kind=cast(DocumentVersionKind, document_version_kind),
        )


def _metadata_object(value: object) -> Mapping[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        return {}
    return cast(Mapping[str, object], value)
