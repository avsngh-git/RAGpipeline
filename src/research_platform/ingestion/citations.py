"""Bounded enrichment of external citation identifiers without paper fabrication."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.openalex import (
    OpenAlexClient,
    OpenAlexNotFound,
    OpenAlexRequestError,
)

LookupStatus = Literal["found", "not_found"]


@dataclass(frozen=True)
class CitationMetadataOutcome:
    identifiers_checked: int
    metadata_found: int
    identifiers_not_found: int
    request_attempts: int


@dataclass(frozen=True)
class UnresolvedCitationTarget:
    namespace: str
    identifier: str


class CitationMetadataRepository:
    """Persist one bounded provider lookup per unresolved external identifier."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def pending_targets(self, limit: int) -> tuple[UnresolvedCitationTarget, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("citation metadata limit must be between 1 and 100")
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT citation.target_namespace, citation.target_identifier
                FROM unresolved_citations AS citation
                WHERE citation.target_namespace = 'openalex'
                  AND citation.resolved_paper_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM unresolved_citation_metadata AS metadata
                      WHERE metadata.target_namespace = citation.target_namespace
                        AND metadata.target_identifier = citation.target_identifier
                        AND metadata.provider = 'openalex'
                  )
                GROUP BY citation.target_namespace, citation.target_identifier
                ORDER BY min(citation.observed_at), citation.target_identifier
                LIMIT $1
                """,
                limit,
            )
        return tuple(
            UnresolvedCitationTarget(
                namespace=row["target_namespace"],
                identifier=row["target_identifier"],
            )
            for row in rows
        )

    async def record_result(
        self,
        target: UnresolvedCitationTarget,
        status: LookupStatus,
        metadata: Mapping[str, object],
        configuration_id: str,
        code_revision: str,
    ) -> bool:
        if target.namespace != "openalex":
            raise ValueError("only OpenAlex citation metadata is currently supported")
        if not configuration_id or not code_revision:
            raise ValueError("configuration ID and code revision are required")
        if status not in {"found", "not_found"}:
            raise ValueError("citation lookup status must be found or not_found")
        if status == "found" and not metadata:
            raise ValueError("found citation metadata must not be empty")
        if status == "not_found" and metadata:
            raise ValueError("not-found citation records must not contain metadata")
        async with self._pool.acquire() as connection:
            stored_id = await connection.fetchval(
                """
                INSERT INTO unresolved_citation_metadata
                    (target_namespace, target_identifier, provider, lookup_status,
                     metadata, retrieved_at, configuration_id, code_revision)
                VALUES ($1, $2, 'openalex', $3, $4::jsonb, $5, $6, $7)
                ON CONFLICT (target_namespace, target_identifier, provider) DO NOTHING
                RETURNING target_identifier
                """,
                target.namespace,
                target.identifier,
                status,
                json.dumps(dict(metadata), sort_keys=True),
                datetime.now(timezone.utc),
                configuration_id,
                code_revision,
            )
        return stored_id is not None


async def enrich_unresolved_citations(
    repository: CitationMetadataRepository,
    client: OpenAlexClient,
    *,
    limit: int,
    code_revision: str,
) -> CitationMetadataOutcome:
    """Fetch source metadata sequentially and checkpoint each completed lookup."""
    if limit > client.request_limit:
        raise ValueError(
            "citation metadata limit cannot exceed the client request limit"
        )
    targets = await repository.pending_targets(limit)
    found = 0
    not_found = 0
    requests_before = client.requests_used
    for target in targets:
        try:
            work = await client.get_work_metadata(target.identifier)
        except OpenAlexNotFound:
            stored = await repository.record_result(
                target,
                "not_found",
                {},
                client.configuration_id,
                code_revision,
            )
            not_found += int(stored)
            continue
        except OpenAlexRequestError:
            # Earlier successful lookups remain checkpointed; a later invocation resumes.
            raise
        if work.openalex_id != target.identifier.removeprefix("https://openalex.org/"):
            raise ValueError("metadata provider returned a different citation endpoint")
        stored = await repository.record_result(
            target,
            "found",
            dict(work.metadata),
            client.configuration_id,
            code_revision,
        )
        found += int(stored)
    return CitationMetadataOutcome(
        identifiers_checked=found + not_found,
        metadata_found=found,
        identifiers_not_found=not_found,
        request_attempts=client.requests_used - requests_before,
    )
