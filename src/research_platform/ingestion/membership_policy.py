"""Code-enforced decisions on papers an agent proposes for ingestion (P35-26).

The agent proposes; this policy decides, records every decision and enqueues the
accepted papers in the same transaction (ADR-0024 items 3-5). Permission is checked
later, at acquisition; the policy refuses only clear cases.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.config import DiscoverySettings
from research_platform.ingestion.generation_index import (
    GenerationQdrantCollection,
    paper_point_id,
)
from research_platform.worker.queue import IngestionQueue

POLICY_REVISION = "online-membership-v1"

DecisionReason = Literal[
    "accepted",
    "unknown_paper",
    "already_indexed",
    "out_of_scope_year",
    "out_of_scope_language",
    "run_paper_limit",
    "duplicate_request",
]


@dataclass(frozen=True)
class MembershipDecision:
    paper_id: str
    decision: Literal["accepted", "refused"]
    reason: DecisionReason


@dataclass(frozen=True)
class PolicyResult:
    request_id: UUID | None
    decisions: tuple[MembershipDecision, ...]


@dataclass(frozen=True)
class _Candidate:
    in_papers: bool
    indexed: bool
    year: int | None
    language: str | None


def decide(
    paper_id: str,
    candidate: _Candidate,
    *,
    settings: DiscoverySettings,
    duplicate: bool,
    accepted_for_run: int,
    max_papers: int,
) -> MembershipDecision:
    """Apply the refusal rules in their fixed order."""
    reason: DecisionReason = "accepted"
    if not candidate.in_papers:
        reason = "unknown_paper"
    elif candidate.indexed:
        reason = "already_indexed"
    elif (
        candidate.year is not None
        and candidate.year < settings.minimum_publication_year
    ):
        reason = "out_of_scope_year"
    elif candidate.language is not None and candidate.language != settings.language:
        reason = "out_of_scope_language"
    elif duplicate:
        reason = "duplicate_request"
    elif accepted_for_run >= max_papers:
        reason = "run_paper_limit"
    return MembershipDecision(
        paper_id, "accepted" if reason == "accepted" else "refused", reason
    )


class MembershipPolicy:
    """Decide on proposed papers and enqueue the accepted ones atomically."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        papers: GenerationQdrantCollection,
        settings: DiscoverySettings,
        *,
        collection_id: UUID,
    ) -> None:
        self._pool = pool
        self._papers = papers
        self._settings = settings
        self._collection_id = collection_id

    async def submit(
        self,
        *,
        run_id: UUID | None,
        requested_by: Literal["run", "api", "terminal"],
        paper_ids: Sequence[str],
        max_papers: int,
    ) -> PolicyResult:
        if max_papers < 1:
            raise ValueError("max_papers must be positive")
        normalized = [_normalize(paper_id) for paper_id in paper_ids]
        if not normalized:
            raise ValueError("at least one paper ID is required")
        points = await self._paper_points(normalized)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    f"membership-policy:{self._collection_id}",
                )
                catalog = await _catalog(connection, normalized)
                accepted_for_run = (
                    0
                    if run_id is None
                    else int(
                        await connection.fetchval(
                            """
                            SELECT count(*) FROM ingestion_decisions
                            WHERE run_id = $1 AND decision = 'accepted'
                            """,
                            run_id,
                        )
                    )
                )
                pending = await _pending_paper_ids(connection, self._collection_id)
                decisions: list[MembershipDecision] = []
                for paper_id in normalized:
                    point = points.get(paper_id)
                    year, language = catalog.get(paper_id, (None, None))
                    if point is not None and year is None:
                        payload_year = point.get("publication_year")
                        year = payload_year if isinstance(payload_year, int) else None
                    decision = decide(
                        paper_id,
                        _Candidate(
                            in_papers=point is not None,
                            indexed=point is not None
                            and point.get("indexed_generation") is not None,
                            year=year,
                            language=language,
                        ),
                        settings=self._settings,
                        duplicate=paper_id in pending,
                        accepted_for_run=accepted_for_run,
                        max_papers=max_papers,
                    )
                    if decision.decision == "accepted":
                        accepted_for_run += 1
                        pending.add(paper_id)
                    decisions.append(decision)
                accepted = [d.paper_id for d in decisions if d.decision == "accepted"]
                request_id = None
                if accepted:
                    request_id = await IngestionQueue.enqueue(
                        connection,
                        collection_id=self._collection_id,
                        run_id=run_id,
                        requested_by=requested_by,
                        paper_ids=accepted,
                    )
                await connection.executemany(
                    """
                    INSERT INTO ingestion_decisions
                        (request_id, run_id, paper_id, decision, reason, policy_revision)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    [
                        (
                            request_id if decision.decision == "accepted" else None,
                            run_id,
                            decision.paper_id,
                            decision.decision,
                            decision.reason,
                            POLICY_REVISION,
                        )
                        for decision in decisions
                    ],
                )
        return PolicyResult(request_id, tuple(decisions))

    async def _paper_points(
        self, paper_ids: Sequence[str]
    ) -> dict[str, Mapping[str, object]]:
        configuration_id = self._papers.configuration.configuration_id
        matches = await self._papers.retrieve(
            [paper_point_id(paper_id, configuration_id) for paper_id in paper_ids]
        )
        return {
            cast(str, match.payload["paper_id"]): match.payload
            for match in matches
            if isinstance(match.payload.get("paper_id"), str)
        }


def _normalize(paper_id: str) -> str:
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError("paper IDs must be non-empty strings")
    return paper_id.strip().removeprefix("https://openalex.org/")


async def _catalog(
    connection: asyncpg.Connection, paper_ids: Sequence[str]
) -> dict[str, tuple[int | None, str | None]]:
    rows = await connection.fetch(
        """
        SELECT paper.id, paper.publication_year,
               COALESCE(revision.metadata, paper.metadata) AS metadata
        FROM papers AS paper
        LEFT JOIN LATERAL (
            SELECT metadata FROM paper_metadata_revisions
            WHERE paper_id = paper.id ORDER BY revision DESC LIMIT 1
        ) AS revision ON TRUE
        WHERE paper.id = ANY($1::text[])
        """,
        list(paper_ids),
    )
    result: dict[str, tuple[int | None, str | None]] = {}
    for row in rows:
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        language = metadata.get("language") if isinstance(metadata, dict) else None
        year = row["publication_year"]
        result[str(row["id"])] = (
            year if isinstance(year, int) else None,
            language if isinstance(language, str) else None,
        )
    return result


async def _pending_paper_ids(
    connection: asyncpg.Connection, collection_id: UUID
) -> set[str]:
    rows = await connection.fetch(
        """
        SELECT DISTINCT unnest(paper_ids) AS paper_id FROM ingestion_requests
        WHERE collection_id = $1 AND status IN ('pending', 'claimed')
        """,
        collection_id,
    )
    return {str(row["paper_id"]) for row in rows}
