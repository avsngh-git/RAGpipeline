"""Snapshot-aware, one-hop reads from locally stored citation relationships."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.identity import is_valid_paper_id
from research_platform.search.paper_reads import (
    PaperIdentityConflict,
    PaperReadStatus,
    SnapshotNotFound,
)

_MAX_CITATION_PAGE_SIZE = 100
_LOCAL_REFERENCES_NOTE = (
    "References include only resolved and unresolved relationships stored locally."
)
_LOCAL_CITATIONS_NOTE = (
    "Incoming citations include only locally observed resolved or stored unresolved "
    "edges; they are not a complete global citation list."
)


class CitationDirection(str, Enum):
    """Direction of a one-hop paper graph read from the requested paper."""

    REFERENCES = "references"
    CITATIONS = "citations"


class CitationEndpointStatus(str, Enum):
    """Snapshot membership state for a graph endpoint."""

    IN_SNAPSHOT = "in_snapshot"
    OUTSIDE_SNAPSHOT = "outside_snapshot"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class CitationGraphCursor:
    """Keyset cursor bound to one snapshot, source paper and direction."""

    snapshot_id: UUID
    paper_id: str
    direction: CitationDirection
    endpoint_kind: Literal["external", "paper"]
    endpoint_identifier: str
    edge_source: str

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, UUID):
            raise ValueError("cursor snapshot_id must be a UUID")
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("cursor paper_id must be a canonical OpenAlex work ID")
        if not isinstance(self.direction, CitationDirection):
            raise ValueError("cursor direction must be a CitationDirection")
        if self.endpoint_kind not in ("external", "paper"):
            raise ValueError("cursor endpoint_kind is unsupported")
        if (
            not isinstance(self.endpoint_identifier, str)
            or not self.endpoint_identifier
        ):
            raise ValueError("cursor endpoint_identifier must be non-empty")
        if not isinstance(self.edge_source, str) or not self.edge_source:
            raise ValueError("cursor edge_source must be non-empty")


@dataclass(frozen=True)
class CitationGraphEndpoint:
    """Resolved local metadata or an explicitly unresolved external identifier."""

    status: CitationEndpointStatus
    paper_id: str | None
    title: str | None
    publication_year: int | None
    external_namespace: str | None = None
    external_identifier: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, CitationEndpointStatus):
            raise ValueError("status must be a CitationEndpointStatus")
        if self.title is not None and not isinstance(self.title, str):
            raise ValueError("title must be text or null")
        if self.publication_year is not None and (
            isinstance(self.publication_year, bool)
            or not isinstance(self.publication_year, int)
            or self.publication_year < 0
        ):
            raise ValueError("publication_year must be non-negative or null")
        if self.status is CitationEndpointStatus.UNRESOLVED:
            if (
                self.paper_id is not None
                or not isinstance(self.external_namespace, str)
                or not self.external_namespace
                or not isinstance(self.external_identifier, str)
                or not self.external_identifier
                or self.title is not None
                or self.publication_year is not None
            ):
                raise ValueError("unresolved endpoints require only an external ID")
        elif (
            not is_valid_paper_id(self.paper_id)
            or self.external_namespace is not None
            or self.external_identifier is not None
        ):
            raise ValueError("resolved endpoints require one canonical paper ID")


@dataclass(frozen=True)
class CitationGraphEdge:
    """One stored relationship and its other endpoint."""

    endpoint: CitationGraphEndpoint
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, CitationGraphEndpoint):
            raise ValueError("endpoint must be a CitationGraphEndpoint")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("edge source must be non-empty")


@dataclass(frozen=True)
class CitationGraphPage:
    """One bounded page of stored graph edges and its source membership state."""

    snapshot_id: UUID
    paper_id: str
    direction: CitationDirection
    source_status: PaperReadStatus
    limit: int
    edges: tuple[CitationGraphEdge, ...]
    next_cursor: CitationGraphCursor | None
    coverage_note: str

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, UUID):
            raise ValueError("snapshot_id must be a UUID")
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if not isinstance(self.direction, CitationDirection):
            raise ValueError("direction must be a CitationDirection")
        if not isinstance(self.source_status, PaperReadStatus):
            raise ValueError("source_status must be a PaperReadStatus")
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= _MAX_CITATION_PAGE_SIZE
        ):
            raise ValueError("limit is outside the citation page bounds")
        if not isinstance(self.edges, tuple) or len(self.edges) > self.limit:
            raise ValueError("edges must be a bounded tuple")
        if any(not isinstance(edge, CitationGraphEdge) for edge in self.edges):
            raise ValueError("edges must contain CitationGraphEdge values")
        if self.next_cursor is not None and not isinstance(
            self.next_cursor, CitationGraphCursor
        ):
            raise ValueError("next_cursor must be a CitationGraphCursor or null")
        if self.next_cursor is not None and (
            self.next_cursor.snapshot_id != self.snapshot_id
            or self.next_cursor.paper_id != self.paper_id
            or self.next_cursor.direction is not self.direction
        ):
            raise ValueError("next_cursor must match its graph page")
        if self.source_status is PaperReadStatus.UNKNOWN and (
            self.edges or self.next_cursor is not None
        ):
            raise ValueError("unknown source papers cannot have graph edges")
        if not isinstance(self.coverage_note, str) or not self.coverage_note.strip():
            raise ValueError("coverage_note must be non-empty")

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


_SOURCE_PAPER_SQL = """
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
       item.paper_id AS snapshot_paper_id
FROM requested_snapshot
LEFT JOIN bounded_candidates AS candidate ON TRUE
LEFT JOIN papers AS paper ON paper.id = candidate.paper_id
LEFT JOIN snapshot_items AS item
  ON item.snapshot_id = requested_snapshot.snapshot_id
 AND item.paper_id = candidate.paper_id
"""

_PUBLIC_PAPER_IDS_CTE = """
WITH public_paper_ids AS (
    SELECT paper.id AS local_paper_id,
           COALESCE(
               CASE WHEN paper.openalex_id ~ '^W[0-9]+$'
                    THEN paper.openalex_id END,
               fallback.paper_id
           ) AS paper_id
    FROM papers AS paper
    LEFT JOIN LATERAL (
        SELECT identifier.normalized_identifier AS paper_id
        FROM paper_identifiers AS identifier
        WHERE identifier.paper_id = paper.id
          AND identifier.namespace = 'openalex'
          AND identifier.normalized_identifier ~ '^W[0-9]+$'
        ORDER BY identifier.normalized_identifier
        LIMIT 1
    ) AS fallback ON TRUE
    WHERE paper.openalex_id ~ '^W[0-9]+$'
       OR fallback.paper_id IS NOT NULL
)
"""

_REFERENCES_SQL = (
    _PUBLIC_PAPER_IDS_CTE
    + """
, graph_edges AS (
    SELECT 'paper'::text AS endpoint_kind,
           public.paper_id AS endpoint_identifier,
           CASE WHEN member.paper_id IS NULL THEN 'outside_snapshot'
                ELSE 'in_snapshot' END AS endpoint_status,
           endpoint.title,
           endpoint.publication_year,
           NULL::text AS external_namespace,
           NULL::text AS external_identifier,
           citation.source AS edge_source
    FROM citations AS citation
    JOIN papers AS endpoint ON endpoint.id = citation.cited_paper_id
    JOIN public_paper_ids AS public ON public.local_paper_id = endpoint.id
    LEFT JOIN snapshot_items AS member
      ON member.snapshot_id = $2 AND member.paper_id = endpoint.id
    WHERE citation.citing_paper_id = $1

    UNION ALL

    SELECT 'external'::text AS endpoint_kind,
           unresolved.target_namespace || ':' || unresolved.target_identifier
               AS endpoint_identifier,
           'unresolved'::text AS endpoint_status,
           NULL::text AS title,
           NULL::integer AS publication_year,
           unresolved.target_namespace AS external_namespace,
           unresolved.target_identifier AS external_identifier,
           unresolved.source AS edge_source
    FROM unresolved_citations AS unresolved
    WHERE unresolved.citing_paper_id = $1
      AND unresolved.resolved_paper_id IS NULL
)
SELECT endpoint_kind, endpoint_identifier, endpoint_status, title,
       publication_year, external_namespace, external_identifier, edge_source
FROM graph_edges
WHERE ($3::text IS NULL
       OR (endpoint_kind, endpoint_identifier, edge_source) > ($3, $4, $5))
ORDER BY endpoint_kind, endpoint_identifier, edge_source
LIMIT $6
"""
)

_CITATIONS_SQL = (
    _PUBLIC_PAPER_IDS_CTE
    + """
, graph_edges AS (
    SELECT 'paper'::text AS endpoint_kind,
           public.paper_id AS endpoint_identifier,
           CASE WHEN member.paper_id IS NULL THEN 'outside_snapshot'
                ELSE 'in_snapshot' END AS endpoint_status,
           endpoint.title,
           endpoint.publication_year,
           NULL::text AS external_namespace,
           NULL::text AS external_identifier,
           citation.source AS edge_source
    FROM citations AS citation
    JOIN papers AS endpoint ON endpoint.id = citation.citing_paper_id
    JOIN public_paper_ids AS public ON public.local_paper_id = endpoint.id
    LEFT JOIN snapshot_items AS member
      ON member.snapshot_id = $3 AND member.paper_id = endpoint.id
    WHERE citation.cited_paper_id = $1

    UNION ALL

    SELECT 'paper'::text AS endpoint_kind,
           public.paper_id AS endpoint_identifier,
           CASE WHEN member.paper_id IS NULL THEN 'outside_snapshot'
                ELSE 'in_snapshot' END AS endpoint_status,
           endpoint.title,
           endpoint.publication_year,
           NULL::text AS external_namespace,
           NULL::text AS external_identifier,
           unresolved.source AS edge_source
    FROM unresolved_citations AS unresolved
    JOIN papers AS endpoint ON endpoint.id = unresolved.citing_paper_id
    JOIN public_paper_ids AS public ON public.local_paper_id = endpoint.id
    LEFT JOIN snapshot_items AS member
      ON member.snapshot_id = $3 AND member.paper_id = endpoint.id
    WHERE unresolved.target_namespace = 'openalex'
      AND unresolved.target_identifier = $2
      AND unresolved.resolved_paper_id IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM citations AS resolved
          WHERE resolved.citing_paper_id = unresolved.citing_paper_id
            AND resolved.cited_paper_id = $1
      )
)
SELECT endpoint_kind, endpoint_identifier, endpoint_status, title,
       publication_year, external_namespace, external_identifier, edge_source
FROM graph_edges
WHERE ($4::text IS NULL
       OR (endpoint_kind, endpoint_identifier, edge_source) > ($4, $5, $6))
ORDER BY endpoint_kind, endpoint_identifier, edge_source
LIMIT $7
"""
)


class CitationGraphReader:
    """Read paginated references/citations from stored local graph records only."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def read_one_hop(
        self,
        snapshot_id: UUID,
        paper_id: str,
        direction: CitationDirection,
        *,
        limit: int = 20,
        cursor: CitationGraphCursor | None = None,
    ) -> CitationGraphPage:
        """Read one bounded page without fetching or synthesizing source text."""
        if not isinstance(snapshot_id, UUID):
            raise ValueError("snapshot_id must be a UUID")
        if not is_valid_paper_id(paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if not isinstance(direction, CitationDirection):
            raise ValueError("direction must be a CitationDirection")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_CITATION_PAGE_SIZE
        ):
            raise ValueError("limit must be between 1 and 100")
        if cursor is not None and (
            not isinstance(cursor, CitationGraphCursor)
            or cursor.snapshot_id != snapshot_id
            or cursor.paper_id != paper_id
            or cursor.direction is not direction
        ):
            raise ValueError("cursor does not match the graph request")

        async with self._pool.acquire() as connection:
            async with connection.transaction(
                isolation="repeatable_read", readonly=True
            ):
                source = await connection.fetchrow(
                    _SOURCE_PAPER_SQL, snapshot_id, paper_id
                )
                if source is None:
                    raise RuntimeError("paper graph source query returned no row")
                if not source["snapshot_exists"]:
                    raise SnapshotNotFound("snapshot does not exist")
                resolved_count = source["resolved_count"]
                if resolved_count > 1:
                    raise PaperIdentityConflict(
                        "public paper ID resolves to multiple local paper records"
                    )
                if resolved_count == 0:
                    return _empty_graph_page(snapshot_id, paper_id, direction, limit)
                local_paper_id = source["local_paper_id"]
                if not isinstance(local_paper_id, str):
                    raise RuntimeError("resolved graph source lacks a local paper ID")
                source_status = (
                    PaperReadStatus.IN_SNAPSHOT
                    if source["snapshot_paper_id"] is not None
                    else PaperReadStatus.OUTSIDE_SNAPSHOT
                )

                if direction is CitationDirection.REFERENCES:
                    cursor_values = _cursor_values(cursor)
                    rows = await connection.fetch(
                        _REFERENCES_SQL,
                        local_paper_id,
                        snapshot_id,
                        *cursor_values,
                        limit + 1,
                    )
                else:
                    cursor_values = _cursor_values(cursor)
                    rows = await connection.fetch(
                        _CITATIONS_SQL,
                        local_paper_id,
                        paper_id,
                        snapshot_id,
                        *cursor_values,
                        limit + 1,
                    )

        has_more = len(rows) > limit
        page_rows = rows[:limit]
        edges = tuple(_edge_from_row(row) for row in page_rows)
        next_cursor = None
        if has_more and page_rows:
            last_row = page_rows[-1]
            next_cursor = CitationGraphCursor(
                snapshot_id=snapshot_id,
                paper_id=paper_id,
                direction=direction,
                endpoint_kind=cast(
                    Literal["external", "paper"], last_row["endpoint_kind"]
                ),
                endpoint_identifier=last_row["endpoint_identifier"],
                edge_source=last_row["edge_source"],
            )
        return CitationGraphPage(
            snapshot_id=snapshot_id,
            paper_id=paper_id,
            direction=direction,
            source_status=source_status,
            limit=limit,
            edges=edges,
            next_cursor=next_cursor,
            coverage_note=_coverage_note(direction),
        )


def _cursor_values(
    cursor: CitationGraphCursor | None,
) -> tuple[str | None, str | None, str | None]:
    if cursor is None:
        return (None, None, None)
    return (
        cursor.endpoint_kind,
        cursor.endpoint_identifier,
        cursor.edge_source,
    )


def _edge_from_row(row: Mapping[str, object]) -> CitationGraphEdge:
    endpoint_kind = row["endpoint_kind"]
    endpoint_identifier = row["endpoint_identifier"]
    edge_source = row["edge_source"]
    if not isinstance(endpoint_identifier, str) or not isinstance(edge_source, str):
        raise RuntimeError("citation graph query returned invalid endpoint identity")

    if endpoint_kind == "external":
        namespace = row["external_namespace"]
        identifier = row["external_identifier"]
        if not isinstance(namespace, str) or not isinstance(identifier, str):
            raise RuntimeError("unresolved citation endpoint lacks its external ID")
        return CitationGraphEdge(
            endpoint=CitationGraphEndpoint(
                status=CitationEndpointStatus.UNRESOLVED,
                paper_id=None,
                title=None,
                publication_year=None,
                external_namespace=namespace,
                external_identifier=identifier,
            ),
            source=edge_source,
        )

    if endpoint_kind != "paper":
        raise RuntimeError("citation graph query returned an unknown endpoint kind")
    status_value = row["endpoint_status"]
    if status_value not in ("in_snapshot", "outside_snapshot"):
        raise RuntimeError("resolved citation endpoint has an invalid status")
    title_value = row["title"]
    year_value = row["publication_year"]
    return CitationGraphEdge(
        endpoint=CitationGraphEndpoint(
            status=CitationEndpointStatus(status_value),
            paper_id=endpoint_identifier,
            title=title_value if isinstance(title_value, str) else None,
            publication_year=cast(int | None, year_value),
        ),
        source=edge_source,
    )


def _empty_graph_page(
    snapshot_id: UUID,
    paper_id: str,
    direction: CitationDirection,
    limit: int,
) -> CitationGraphPage:
    return CitationGraphPage(
        snapshot_id=snapshot_id,
        paper_id=paper_id,
        direction=direction,
        source_status=PaperReadStatus.UNKNOWN,
        limit=limit,
        edges=(),
        next_cursor=None,
        coverage_note=_coverage_note(direction),
    )


def _coverage_note(direction: CitationDirection) -> str:
    if direction is CitationDirection.CITATIONS:
        return _LOCAL_CITATIONS_NOTE
    return _LOCAL_REFERENCES_NOTE
