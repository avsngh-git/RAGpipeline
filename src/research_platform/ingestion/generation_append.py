"""Append ingested papers as the next published generation (P35-25, ADR-0023/0024).

A child snapshot copies the published generation's snapshot exactly, adds the newly
ingested papers, and is finalized automatically by policy. Its index integrity is
checked by generation verification before the published pointer moves, so the legacy
per-snapshot index is not required.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.generation_build import (
    GenerationInputRepository,
    build_generation_passages,
)
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationQdrantCollection,
)
from research_platform.ingestion.generation_publication import (
    publish_generation,
    verify_generation,
)
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.indexing import VectorEmbedder
from research_platform.ingestion.online_ingestion import PaperIngestOutcome
from research_platform.ingestion.paper_index import PaperIndexRepository, sync_papers
from research_platform.ingestion.provenance import code_revision
from research_platform.ingestion.snapshots import SnapshotRepository
from research_platform.ingestion.sparse_build import (
    SparseEncoder,
    compute_lexical_averages,
)

ONLINE_REVIEWER = "policy:online-ingestion-v1"
DRIFT_LIMIT = 0.10
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppendReport:
    parent_generation: int
    generation: int | None
    snapshot_id: UUID | None
    added_papers: tuple[str, ...]
    outcomes: tuple[PaperIngestOutcome, ...]
    average_length_drift: float


class AppendValidationError(RuntimeError):
    """The child snapshot failed validation for reasons beyond the new papers."""


class _AverageSource(Protocol):
    async def evidence_average_length(self, snapshot_id: UUID) -> float: ...


class _LexicalAverages:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def evidence_average_length(self, snapshot_id: UUID) -> float:
        averages = await compute_lexical_averages(
            GenerationInputRepository(self._pool),
            PaperIndexRepository(self._pool),
            snapshot_id,
        )
        return averages.evidence_average_length


class GenerationAppender:
    """Turn ingested papers into a child snapshot and the next published generation."""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        registry: GenerationRegistry,
        snapshots: SnapshotRepository,
        configuration: GenerationIndexConfiguration,
        passages: GenerationQdrantCollection,
        papers: GenerationQdrantCollection,
        embedder: VectorEmbedder,
        sparse_encoder: SparseEncoder | None,
        averages: _AverageSource | None = None,
    ) -> None:
        self._pool = pool
        self._registry = registry
        self._snapshots = snapshots
        self._configuration = configuration
        self._passages = passages
        self._papers = papers
        self._embedder = embedder
        self._sparse_encoder = sparse_encoder
        self._averages = averages or _LexicalAverages(pool)

    async def append(
        self,
        collection_id: UUID,
        outcomes: Sequence[PaperIngestOutcome],
        *,
        request_id: UUID,
    ) -> AppendReport:
        configuration_id = self._configuration.configuration_id
        async with self._append_lock(configuration_id):
            published = await self._registry.published(collection_id, configuration_id)
            if published is None:
                raise ValueError("the collection has no published generation")
            ingested = [outcome for outcome in outcomes if outcome.status == "ingested"]
            if not ingested:
                return AppendReport(
                    published.generation, None, None, (), tuple(outcomes), 0.0
                )
            await self._supersede_unpublished(collection_id, published.generation)
            snapshot_id, added, results = await self._child_snapshot(
                published.snapshot_id, outcomes, request_id
            )
            if not added:
                return AppendReport(published.generation, None, None, (), results, 0.0)
            report = await build_generation_passages(
                registry=self._registry,
                inputs=GenerationInputRepository(self._pool),
                passages=self._passages,
                embedder=self._embedder,
                configuration=self._configuration,
                collection_id=collection_id,
                snapshot_id=snapshot_id,
                sparse_encoder=self._sparse_encoder,
            )
            generation = report.generation
            try:
                await sync_papers(
                    repository=PaperIndexRepository(self._pool),
                    papers=self._papers,
                    embedder=self._embedder,
                    configuration=self._configuration,
                    generation=generation,
                    snapshot_id=snapshot_id,
                    sparse_encoder=self._sparse_encoder,
                )
            except BaseException:
                await self._registry.mark_failed(
                    collection_id, configuration_id, generation, reason="paper_sync"
                )
                raise
            verification = await verify_generation(
                registry=self._registry,
                inputs=GenerationInputRepository(self._pool),
                papers_repository=PaperIndexRepository(self._pool),
                passages=self._passages,
                papers=self._papers,
                collection_id=collection_id,
                configuration_id=configuration_id,
                generation=generation,
            )
            if not verification.passed:
                raise RuntimeError(f"generation {generation} failed verification")
            drift = await self._drift(snapshot_id)
            if drift > DRIFT_LIMIT:
                _LOG.warning(
                    "evidence average length drifted; a new configuration is recommended",
                    extra={"generation": generation, "drift": round(drift, 4)},
                )
                await self._record_details(
                    collection_id,
                    generation,
                    {
                        "new_configuration_recommended": True,
                        "average_length_drift": drift,
                    },
                )
            await publish_generation(
                self._registry, collection_id, configuration_id, generation
            )
            return AppendReport(
                published.generation, generation, snapshot_id, added, results, drift
            )

    async def _child_snapshot(
        self,
        parent_snapshot_id: UUID,
        outcomes: Sequence[PaperIngestOutcome],
        request_id: UUID,
    ) -> tuple[UUID, tuple[str, ...], tuple[PaperIngestOutcome, ...]]:
        async with self._pool.acquire() as connection:
            parent_configuration_id = await connection.fetchval(
                "SELECT configuration_id FROM snapshots WHERE id = $1",
                parent_snapshot_id,
            )
        snapshot_id = await self._snapshots.create_variant_draft(
            parent_snapshot_id,
            name=f"online-ingestion-{request_id}",
            configuration_id=parent_configuration_id,
            configuration=await self._snapshots.configuration_for(parent_snapshot_id),
            code_revision=code_revision(),
        )
        members = await self._member_ids(snapshot_id)
        results: list[PaperIngestOutcome] = []
        added: dict[str, PaperIngestOutcome] = {}
        for outcome in outcomes:
            if outcome.status != "ingested":
                results.append(outcome)
                continue
            if (
                outcome.document_id is None
                or outcome.extraction_id is None
                or outcome.chunking_configuration_id is None
            ):
                raise ValueError("an ingested outcome lacks its document identities")
            paper_id = await self._catalog_paper_id(outcome.document_id)
            if paper_id in members or paper_id in added:
                results.append(replace(outcome, reason="already_member"))
                continue
            await self._snapshots.add_member(
                snapshot_id,
                paper_id=paper_id,
                document_id=outcome.document_id,
                extraction_id=outcome.extraction_id,
                selection_reason=f"online-ingestion:{request_id}",
            )
            await self._snapshots.set_chunking_configuration(
                snapshot_id,
                outcome.document_id,
                outcome.extraction_id,
                outcome.chunking_configuration_id,
            )
            added[paper_id] = outcome
        report = await self._snapshots.validate(
            snapshot_id,
            minimum_papers=len(members) + len(added),
            require_snapshot_index=False,
        )
        rejected = {
            issue.paper_id: issue.code
            for issue in report.issues
            if issue.paper_id in added
        }
        for paper_id, code in rejected.items():
            await self._snapshots.remove_member(snapshot_id, paper_id)
            results.append(
                replace(
                    added.pop(paper_id), status="failed", reason=f"validation:{code}"
                )
            )
        results.extend(added.values())
        if not added:
            return snapshot_id, (), tuple(results)
        try:
            await self._snapshots.finalize(
                snapshot_id,
                reviewer=ONLINE_REVIEWER,
                minimum_papers=len(members) + len(added),
                require_snapshot_index=False,
            )
        except ValueError as error:
            raise AppendValidationError(
                "the child snapshot failed validation"
            ) from error
        return snapshot_id, tuple(sorted(added)), tuple(results)

    async def _member_ids(self, snapshot_id: UUID) -> set[str]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT paper_id FROM snapshot_items WHERE snapshot_id = $1",
                snapshot_id,
            )
        return {str(row["paper_id"]) for row in rows}

    async def _catalog_paper_id(self, document_id: UUID) -> str:
        async with self._pool.acquire() as connection:
            paper_id = await connection.fetchval(
                "SELECT paper_id FROM documents WHERE id = $1", document_id
            )
        if not isinstance(paper_id, str):
            raise ValueError("ingested document has no catalog paper")
        return paper_id

    async def _supersede_unpublished(
        self, collection_id: UUID, published_generation: int
    ) -> None:
        """Fail generations a crashed append left above the published pointer."""
        async with self._pool.acquire() as connection:
            stale = await connection.fetch(
                """
                SELECT generation FROM index_generations
                WHERE collection_id = $1 AND configuration_id = $2
                  AND generation > $3 AND state IN ('building', 'verified')
                ORDER BY generation
                """,
                collection_id,
                self._configuration.configuration_id,
                published_generation,
            )
        for row in stale:
            await self._registry.mark_failed(
                collection_id,
                self._configuration.configuration_id,
                int(row["generation"]),
                reason="superseded",
            )

    async def _drift(self, snapshot_id: UUID) -> float:
        lexical = self._configuration.lexical
        if lexical is None:
            return 0.0
        average = await self._averages.evidence_average_length(snapshot_id)
        return abs(average - lexical.evidence_average_length) / (
            lexical.evidence_average_length
        )

    async def _record_details(
        self, collection_id: UUID, generation: int, details: dict[str, object]
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE index_generations SET details = details || $4::jsonb
                WHERE collection_id = $1 AND configuration_id = $2 AND generation = $3
                """,
                collection_id,
                self._configuration.configuration_id,
                generation,
                json.dumps(details),
            )

    @asynccontextmanager
    async def _append_lock(self, configuration_id: str) -> AsyncIterator[None]:
        """Serialize appends per configuration on a dedicated database session."""
        key = f"generation-append:{configuration_id}"
        async with self._pool.acquire() as connection:
            await connection.execute(
                "SELECT pg_advisory_lock(hashtextextended($1, 0))", key
            )
            try:
                yield
            finally:
                try:
                    await connection.execute(
                        "SELECT pg_advisory_unlock(hashtextextended($1, 0))", key
                    )
                except BaseException:
                    connection.terminate()
                    raise
