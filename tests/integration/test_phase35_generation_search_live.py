"""Live coverage for authorization and Qdrant-served evidence content (P35-09)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import httpx
import pytest

from research_platform.ingestion.generation_build import (
    GenerationInputRepository,
    build_generation_passages,
)
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationQdrantCollection,
)
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.indexing import (
    IndexConfiguration,
    SnapshotAccessDenied,
)
from research_platform.persistence.migrations import apply_migrations
from research_platform.search.generation_search import (
    PassageAuthorizer,
    QdrantContentReader,
)

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")
TEST_QDRANT_URL = os.environ.get("RESEARCH_PLATFORM_TEST_QDRANT_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL or not TEST_QDRANT_URL,
        reason="requires the dedicated disposable PostgreSQL and Qdrant services",
    ),
]


class _Embedder:
    async def embed(
        self, texts: Sequence[str], *, configuration: IndexConfiguration
    ) -> Sequence[Sequence[float]]:
        return [(1.0, 0.0) for _ in texts]


def test_reader_serves_authorized_generation_content(evidence_snapshots) -> None:
    assert TEST_DATABASE_URL is not None and TEST_QDRANT_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=3)
        suffix = uuid4().hex[:12]
        configuration = GenerationIndexConfiguration(
            passages_collection=f"phase35-search-passages-{suffix}",
            papers_collection=f"phase35-search-papers-{suffix}",
            embedding_model="integration-fixture",
            embedding_revision="v1",
            preprocessing_revision="raw-text-v1",
            vector_size=2,
            distance="Cosine",
            batch_size=4,
            maximum_input_tokens=32,
        )
        async with httpx.AsyncClient(base_url=TEST_QDRANT_URL, timeout=30) as http:
            passages = GenerationQdrantCollection(configuration, "passages", http)
            try:
                paper = await evidence_snapshots.paper(
                    pool, title="Served", sections=["alpha beta", "gamma delta"]
                )
                outsider = await evidence_snapshots.paper(
                    pool, title="Outsider", sections=["epsilon zeta"]
                )
                snapshot_id = await evidence_snapshots.snapshot(pool, [paper])
                draft_id = await evidence_snapshots.snapshot(
                    pool, [paper], finalized=False
                )
                registry = GenerationRegistry(pool)
                await build_generation_passages(
                    registry=registry,
                    inputs=GenerationInputRepository(pool),
                    passages=passages,
                    embedder=_Embedder(),
                    configuration=configuration,
                    collection_id=await registry.ensure_collection(
                        f"phase35-search-{suffix}"
                    ),
                    snapshot_id=snapshot_id,
                )
                authorizer = PassageAuthorizer(pool)
                reader = QdrantContentReader(passages, authorizer, configuration)
                ids = list(reversed(paper.evidence_ids))
                served = await reader.read(snapshot_id, 1, ids)
                assert [item.evidence_id for item in served] == ids
                assert [item.text for item in served] == [paper.texts[i] for i in ids]
                assert {item.payload["snapshot_id"] for item in served} == {
                    str(snapshot_id)
                }

                with pytest.raises(PermissionError):
                    await authorizer.authorize(
                        snapshot_id, [*paper.evidence_ids, *outsider.evidence_ids]
                    )
                with pytest.raises(SnapshotAccessDenied):
                    await authorizer.authorize(draft_id, list(paper.evidence_ids))
            finally:
                await http.delete(f"/collections/{passages.name}")
                await pool.close()

    asyncio.run(exercise())
