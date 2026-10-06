"""Live PostgreSQL and Qdrant coverage for appending a generation (P35-25)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Sequence
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import httpx
import pytest

from research_platform.ingestion.evidence import ChunkingConfig
from research_platform.ingestion.generation_append import (
    ONLINE_REVIEWER,
    GenerationAppender,
)
from research_platform.ingestion.generation_build import (
    GenerationInputRepository,
    build_generation_passages,
)
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationQdrantCollection,
    generation_filter,
)
from research_platform.ingestion.generation_publication import (
    publish_generation,
    verify_generation,
)
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.indexing import IndexConfiguration
from research_platform.ingestion.online_ingestion import PaperIngestOutcome
from research_platform.ingestion.paper_index import PaperIndexRepository, sync_papers
from research_platform.ingestion.snapshots import SnapshotRepository
from research_platform.ingestion.sparse_build import (
    SparseEncoder,
    compute_lexical_averages,
)
from research_platform.persistence.migrations import apply_migrations
from research_platform.search.sparse_lexical import VocabularyRepository

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")
TEST_QDRANT_URL = os.environ.get("RESEARCH_PLATFORM_TEST_QDRANT_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL or not TEST_QDRANT_URL,
        reason="requires the dedicated disposable PostgreSQL and Qdrant services",
    ),
]

FIXTURE_CHUNKING = ChunkingConfig(64, 0, 4)


class _Embedder:
    """Distinct unit-length vectors derived from each text's hash."""

    async def embed(
        self, texts: Sequence[str], *, configuration: IndexConfiguration
    ) -> Sequence[Sequence[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            raw = [digest[index] - 127.5 for index in range(4)]
            norm = sum(value * value for value in raw) ** 0.5
            vectors.append([value / norm for value in raw])
        return vectors


def _configuration(suffix: str, lexical: object = None) -> GenerationIndexConfiguration:
    return GenerationIndexConfiguration(
        passages_collection=f"phase35-append-passages-{suffix}",
        papers_collection=f"phase35-append-papers-{suffix}",
        embedding_model="integration-fixture",
        embedding_revision="v1",
        preprocessing_revision="raw-text-v1",
        vector_size=4,
        distance="Cosine",
        batch_size=8,
        maximum_input_tokens=64,
        lexical=lexical,  # type: ignore[arg-type]
    )


def test_append_publishes_next_generation_and_old_generation_still_reads(
    evidence_snapshots,
) -> None:
    assert TEST_DATABASE_URL is not None and TEST_QDRANT_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=8)
        suffix = uuid4().hex[:12]
        http = httpx.AsyncClient(base_url=TEST_QDRANT_URL, timeout=60)
        configuration = _configuration(suffix)
        try:
            first = await evidence_snapshots.paper(
                pool,
                title="Reranking for retrieval-augmented generation",
                sections=("Cross-encoder reranking improves nDCG@10 over BM25.",),
            )
            second = await evidence_snapshots.paper(
                pool,
                title="Dense passage retrieval",
                sections=("Dense retrieval recall exceeds BM25 on open-domain QA.",),
            )
            parent = await evidence_snapshots.snapshot(
                pool, [first, second], finalized=False
            )
            async with pool.acquire() as connection:
                await connection.execute(
                    """
                    UPDATE snapshots SET configuration = $2::jsonb WHERE id = $1
                    """,
                    parent,
                    json.dumps(
                        {
                            "fixture": True,
                            "index_configuration_id": "sha256:" + "e" * 64,
                        }
                    ),
                )
                await connection.execute(
                    """
                    UPDATE snapshots SET status = 'finalized', finalized_at = now(),
                        finalized_by = 'integration-test'
                    WHERE id = $1
                    """,
                    parent,
                )
            averages = await compute_lexical_averages(
                GenerationInputRepository(pool), PaperIndexRepository(pool), parent
            )
            lexical = averages.settings()
            vocabulary_id = f"test-{suffix}"
            lexical = type(lexical)(
                **{**lexical.to_dict(), "vocabulary_id": vocabulary_id}
            )
            configuration = _configuration(suffix, lexical)
            encoder = SparseEncoder(VocabularyRepository(pool), lexical)
            await encoder.prepare()
            registry = GenerationRegistry(pool)
            collection_id = await registry.ensure_collection(f"append-{suffix}")
            passages = GenerationQdrantCollection(configuration, "passages", http)
            papers = GenerationQdrantCollection(configuration, "papers", http)
            embedder = _Embedder()

            await build_generation_passages(
                registry=registry,
                inputs=GenerationInputRepository(pool),
                passages=passages,
                embedder=embedder,
                configuration=configuration,
                collection_id=collection_id,
                snapshot_id=parent,
                sparse_encoder=encoder,
            )
            await sync_papers(
                repository=PaperIndexRepository(pool),
                papers=papers,
                embedder=embedder,
                configuration=configuration,
                generation=1,
                snapshot_id=parent,
                sparse_encoder=encoder,
            )
            verified = await verify_generation(
                registry=registry,
                inputs=GenerationInputRepository(pool),
                papers_repository=PaperIndexRepository(pool),
                passages=passages,
                papers=papers,
                collection_id=collection_id,
                configuration_id=configuration.configuration_id,
                generation=1,
            )
            assert verified.passed
            await publish_generation(
                registry, collection_id, configuration.configuration_id, 1
            )
            probe = (await embedder.embed(["probe"], configuration=None))[0]  # type: ignore[arg-type]
            before = [
                (match.payload["evidence_id"], match.score)
                for match in await passages.query_dense(
                    probe, filter_=generation_filter(1), limit=20, exact=True
                )
            ]

            third = await evidence_snapshots.paper(
                pool,
                title="Reciprocal rank fusion",
                sections=("Rank fusion combines BM25 and dense retrievers with RRF.",),
            )
            outcome = PaperIngestOutcome(
                third.paper_id,
                "ingested",
                "ingested",
                third.document_id,
                third.extraction_id,
                FIXTURE_CHUNKING.config_id,
            )
            appender = GenerationAppender(
                pool=pool,
                registry=registry,
                snapshots=SnapshotRepository(pool),
                configuration=configuration,
                passages=passages,
                papers=papers,
                embedder=embedder,
                sparse_encoder=encoder,
            )
            report = await appender.append(
                collection_id, (outcome,), request_id=uuid4()
            )

            assert report.parent_generation == 1 and report.generation == 2
            assert report.added_papers == (third.paper_id,)
            published = await registry.published(
                collection_id, configuration.configuration_id
            )
            assert published is not None and published.generation == 2
            async with pool.acquire() as connection:
                child = await connection.fetchrow(
                    "SELECT status, finalized_by FROM snapshots WHERE id = $1",
                    report.snapshot_id,
                )
            assert (child["status"], child["finalized_by"]) == (
                "finalized",
                ONLINE_REVIEWER,
            )
            old_count = len(first.evidence_ids) + len(second.evidence_ids)
            assert await passages.count(generation_filter(1)) == old_count
            assert await passages.count(generation_filter(2)) == old_count + len(
                third.evidence_ids
            )
            after = [
                (match.payload["evidence_id"], match.score)
                for match in await passages.query_dense(
                    probe, filter_=generation_filter(1), limit=20, exact=True
                )
            ]
            assert after == before
        finally:
            for name in (
                configuration.passages_collection,
                configuration.papers_collection,
            ):
                await http.delete(f"/collections/{name}")
            await http.aclose()
            await pool.close()

    asyncio.run(exercise())
