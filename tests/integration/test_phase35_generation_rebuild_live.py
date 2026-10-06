"""Live coverage: published generations rebuild from PostgreSQL alone (P35-10)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from urllib.parse import urlparse
from uuid import UUID, uuid4

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
    generation_filter,
)
from research_platform.ingestion.generation_publication import (
    publish_generation,
    verify_generation,
)
from research_platform.ingestion.generation_rebuild import rebuild_generations
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.indexing import IndexConfiguration
from research_platform.ingestion.paper_index import PaperIndexRepository, sync_papers
from research_platform.persistence.migrations import apply_migrations

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
        return [(1.0, float(len(text) % 5)) for text in texts]


def test_rebuild_reproduces_published_generations(evidence_snapshots) -> None:
    assert TEST_DATABASE_URL is not None and TEST_QDRANT_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=3)
        suffix = uuid4().hex[:12]
        configuration = GenerationIndexConfiguration(
            passages_collection=f"phase35-rebuild-passages-{suffix}",
            papers_collection=f"phase35-rebuild-papers-{suffix}",
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
            papers = GenerationQdrantCollection(configuration, "papers", http)
            registry = GenerationRegistry(pool)
            inputs = GenerationInputRepository(pool)
            paper_repository = PaperIndexRepository(pool)
            collection_id = await registry.ensure_collection(
                f"phase35-rebuild-{suffix}"
            )

            async def publish(snapshot_id: UUID) -> None:
                report = await build_generation_passages(
                    registry=registry,
                    inputs=inputs,
                    passages=passages,
                    embedder=_Embedder(),
                    configuration=configuration,
                    collection_id=collection_id,
                    snapshot_id=snapshot_id,
                )
                await sync_papers(
                    repository=paper_repository,
                    papers=papers,
                    embedder=_Embedder(),
                    configuration=configuration,
                    generation=report.generation,
                    snapshot_id=snapshot_id,
                )
                verified = await verify_generation(
                    registry=registry,
                    inputs=inputs,
                    papers_repository=paper_repository,
                    passages=passages,
                    papers=papers,
                    collection_id=collection_id,
                    configuration_id=configuration.configuration_id,
                    generation=report.generation,
                )
                assert verified.passed
                await publish_generation(
                    registry,
                    collection_id,
                    configuration.configuration_id,
                    report.generation,
                )

            async def visible(generation: int) -> set[str]:
                payloads = await passages.scroll_payloads(
                    filter_=generation_filter(generation), fields=["evidence_id"]
                )
                return {str(payload["evidence_id"]) for payload in payloads}

            try:
                kept = await evidence_snapshots.paper(
                    pool, title="Kept", sections=["alpha beta"]
                )
                removed = await evidence_snapshots.paper(
                    pool, title="Removed", sections=["gamma delta"]
                )
                added = await evidence_snapshots.paper(
                    pool, title="Added", sections=["epsilon zeta"]
                )
                await publish(await evidence_snapshots.snapshot(pool, [kept, removed]))
                await publish(await evidence_snapshots.snapshot(pool, [kept, added]))
                before = (await visible(1), await visible(2))

                arguments = {
                    "registry": registry,
                    "inputs": inputs,
                    "papers_repository": paper_repository,
                    "passages": passages,
                    "papers": papers,
                    "embedder": _Embedder(),
                    "configuration": configuration,
                    "collection_id": collection_id,
                }
                with pytest.raises(ValueError, match="empty collection"):
                    await rebuild_generations(**arguments)  # type: ignore[arg-type]
                await http.delete(f"/collections/{passages.name}")
                await http.delete(f"/collections/{papers.name}")

                rebuilt = await rebuild_generations(**arguments)  # type: ignore[arg-type]

                assert rebuilt.passed
                assert [b.generation for b in rebuilt.builds] == [1, 2]
                assert (await visible(1), await visible(2)) == before
            finally:
                await http.delete(f"/collections/{passages.name}")
                await http.delete(f"/collections/{papers.name}")
                await pool.close()

    asyncio.run(exercise())
