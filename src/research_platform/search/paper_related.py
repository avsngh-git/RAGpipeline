"""Snapshot-bound related-paper reads from stored citation edges."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.identity import is_valid_paper_id
from research_platform.search.paper_reads import (
    PaperIdentityConflict,
    PaperReadStatus,
    SnapshotNotFound,
)

_MAX_RELATED_PAPERS = 20
_COVERAGE_NOTE = "Related papers are based on stored in-corpus citation edges only."


class RelationKind(StrEnum):
    """How two papers are connected by stored citation relationships."""

    SHARED_REFERENCES = "shared_references"
    CO_CITED = "co_cited"


@dataclass(frozen=True)
class RelatedPaper:
    """One snapshot paper ranked by its shared-reference and co-citation counts."""

    paper_id: str
    title: str | None
    publication_year: int | None
    shared_reference_count: int
    co_citation_count: int
    score: int
    relations: tuple[RelationKind, ...]

    def __post_init__(self) -> None:
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if self.title is not None and not isinstance(self.title, str):
            raise ValueError("title must be text or null")
        if self.publication_year is not None and (
            isinstance(self.publication_year, bool)
            or not isinstance(self.publication_year, int)
            or self.publication_year < 0
        ):
            raise ValueError("publication_year must be non-negative or null")
        counts = (self.shared_reference_count, self.co_citation_count, self.score)
        if any(
            isinstance(value, bool) or not isinstance(value, int) for value in counts
        ):
            raise ValueError("relation counts and score must be integers")
        if self.shared_reference_count < 0 or self.co_citation_count < 0:
            raise ValueError("relation counts must be non-negative")
        if self.score != self.shared_reference_count + self.co_citation_count:
            raise ValueError("score must equal the sum of relation counts")
        if not isinstance(self.relations, tuple) or any(
            not isinstance(relation, RelationKind) for relation in self.relations
        ):
            raise ValueError("relations must be a tuple of RelationKind values")
        if self.relations != _relations_for_counts(
            self.shared_reference_count, self.co_citation_count
        ):
            raise ValueError(
                "relations must include exactly the positive relation kinds"
            )


@dataclass(frozen=True)
class RelatedPapersPage:
    """A bounded set of related papers and the source's snapshot membership state."""

    snapshot_id: UUID
    paper_id: str
    source_status: PaperReadStatus
    papers: tuple[RelatedPaper, ...]
    coverage_note: str

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, UUID):
            raise ValueError("snapshot_id must be a UUID")
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if not isinstance(self.source_status, PaperReadStatus):
            raise ValueError("source_status must be a PaperReadStatus")
        if not isinstance(self.papers, tuple) or any(
            not isinstance(paper, RelatedPaper) for paper in self.papers
        ):
            raise ValueError("papers must be a tuple of RelatedPaper values")
        if self.source_status is not PaperReadStatus.IN_SNAPSHOT and self.papers:
            raise ValueError("papers are returned only for an in-snapshot source")
        if not isinstance(self.coverage_note, str) or not self.coverage_note.strip():
            raise ValueError("coverage_note must be non-empty")


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

_RELATED_PAPERS_SQL = (
    _PUBLIC_PAPER_IDS_CTE
    + """
, snapshot_candidates AS (
    SELECT item.paper_id AS local_paper_id,
           public.paper_id,
           paper.title,
           paper.publication_year
    FROM snapshot_items AS item
    JOIN papers AS paper ON paper.id = item.paper_id
    JOIN public_paper_ids AS public ON public.local_paper_id = item.paper_id
    WHERE item.snapshot_id = $1
      AND item.paper_id <> $2
)
SELECT candidate.paper_id,
       candidate.title,
       candidate.publication_year,
       (
           SELECT count(DISTINCT source_reference.cited_paper_id)
           FROM citations AS source_reference
           JOIN citations AS candidate_reference
             ON candidate_reference.cited_paper_id = source_reference.cited_paper_id
           WHERE source_reference.citing_paper_id = $2
             AND candidate_reference.citing_paper_id = candidate.local_paper_id
       ) AS shared_reference_count,
       (
           SELECT count(DISTINCT source_citation.citing_paper_id)
           FROM citations AS source_citation
           JOIN citations AS candidate_citation
             ON candidate_citation.citing_paper_id = source_citation.citing_paper_id
           WHERE source_citation.cited_paper_id = $2
             AND candidate_citation.cited_paper_id = candidate.local_paper_id
             AND source_citation.citing_paper_id <> $2
             AND source_citation.citing_paper_id <> candidate.local_paper_id
       ) AS co_citation_count
FROM snapshot_candidates AS candidate
"""
)


class RelatedPaperReader:
    """Find same-snapshot papers connected by stored resolved citation edges."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def find_related(
        self, snapshot_id: UUID, paper_id: str, *, limit: int = 10
    ) -> RelatedPapersPage:
        """Return related papers ranked by the two stored-edge relation counts."""
        if not isinstance(snapshot_id, UUID):
            raise ValueError("snapshot_id must be a UUID")
        if not is_valid_paper_id(paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        _validate_limit(limit)

        async with self._pool.acquire() as connection:
            async with connection.transaction(
                isolation="repeatable_read", readonly=True
            ):
                source = await connection.fetchrow(
                    _SOURCE_PAPER_SQL, snapshot_id, paper_id
                )
                if source is None:
                    raise RuntimeError("related-paper source query returned no row")
                if not source["snapshot_exists"]:
                    raise SnapshotNotFound("snapshot does not exist")
                resolved_count = source["resolved_count"]
                if resolved_count > 1:
                    raise PaperIdentityConflict(
                        "public paper ID resolves to multiple local paper records"
                    )
                if resolved_count == 0:
                    return _empty_page(snapshot_id, paper_id)
                local_paper_id = source["local_paper_id"]
                if not isinstance(local_paper_id, str):
                    raise RuntimeError("resolved related-paper source lacks local ID")
                source_status = (
                    PaperReadStatus.IN_SNAPSHOT
                    if source["snapshot_paper_id"] is not None
                    else PaperReadStatus.OUTSIDE_SNAPSHOT
                )
                if source_status is PaperReadStatus.OUTSIDE_SNAPSHOT:
                    return _page(snapshot_id, paper_id, source_status, ())

                rows = await connection.fetch(
                    _RELATED_PAPERS_SQL, snapshot_id, local_paper_id
                )

        parsed_papers = (_related_paper_from_row(row) for row in rows)
        papers = tuple(paper for paper in parsed_papers if paper is not None)
        ranked = rank_related(papers, limit)
        return _page(snapshot_id, paper_id, source_status, ranked)


def rank_related(rows: Sequence[RelatedPaper], limit: int) -> tuple[RelatedPaper, ...]:
    """Sort by score, then shared references, then public paper ID; cut to limit."""
    _validate_limit(limit)
    if any(not isinstance(row, RelatedPaper) for row in rows):
        raise ValueError("rows must contain RelatedPaper values")
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                -row.score,
                -row.shared_reference_count,
                row.paper_id,
            ),
        )[:limit]
    )


def _validate_limit(limit: int) -> None:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= _MAX_RELATED_PAPERS
    ):
        raise ValueError("limit must be between 1 and 20")


def _relations_for_counts(
    shared_reference_count: int, co_citation_count: int
) -> tuple[RelationKind, ...]:
    relations: list[RelationKind] = []
    if shared_reference_count > 0:
        relations.append(RelationKind.SHARED_REFERENCES)
    if co_citation_count > 0:
        relations.append(RelationKind.CO_CITED)
    return tuple(relations)


def _related_paper_from_row(row: Mapping[str, object]) -> RelatedPaper | None:
    paper_id = row["paper_id"]
    if not isinstance(paper_id, str):
        raise RuntimeError("related-paper query returned an invalid public paper ID")
    shared_count = row["shared_reference_count"]
    co_citation_count = row["co_citation_count"]
    if (
        isinstance(shared_count, bool)
        or not isinstance(shared_count, int)
        or isinstance(co_citation_count, bool)
        or not isinstance(co_citation_count, int)
    ):
        raise RuntimeError("related-paper query returned invalid relation counts")
    if shared_count + co_citation_count == 0:
        return None
    title_value = row["title"]
    publication_year = row["publication_year"]
    if publication_year is not None and (
        isinstance(publication_year, bool) or not isinstance(publication_year, int)
    ):
        raise RuntimeError("related-paper query returned an invalid publication year")
    return RelatedPaper(
        paper_id=paper_id,
        title=(
            title_value
            if isinstance(title_value, str) and title_value.strip()
            else None
        ),
        publication_year=publication_year,
        shared_reference_count=shared_count,
        co_citation_count=co_citation_count,
        score=shared_count + co_citation_count,
        relations=_relations_for_counts(shared_count, co_citation_count),
    )


def _page(
    snapshot_id: UUID,
    paper_id: str,
    source_status: PaperReadStatus,
    papers: tuple[RelatedPaper, ...],
) -> RelatedPapersPage:
    return RelatedPapersPage(
        snapshot_id=snapshot_id,
        paper_id=paper_id,
        source_status=source_status,
        papers=papers,
        coverage_note=_COVERAGE_NOTE,
    )


def _empty_page(snapshot_id: UUID, paper_id: str) -> RelatedPapersPage:
    return _page(snapshot_id, paper_id, PaperReadStatus.UNKNOWN, ())
