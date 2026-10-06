"""Live coverage for the papers collection sync (P35-07)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import httpx
import pytest

from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationQdrantCollection,
    indexed_paper_filter,
)
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
        return [(1.0, 0.5) for _ in texts]


def test_sync_marks_members_and_keeps_others_metadata_only(evidence_snapshots) -> None:
    assert TEST_DATABASE_URL is not None and TEST_QDRANT_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=3)
        configuration = GenerationIndexConfiguration(
            passages_collection=f"phase35-paper-passages-{uuid4().hex[:12]}",
            papers_collection=f"phase35-paper-papers-{uuid4().hex[:12]}",
            embedding_model="integration-fixture",
            embedding_revision="v1",
            preprocessing_revision="raw-text-v1",
            vector_size=2,
            distance="Cosine",
            batch_size=4,
            maximum_input_tokens=32,
        )
        async with httpx.AsyncClient(base_url=TEST_QDRANT_URL, timeout=30) as http:
            papers = GenerationQdrantCollection(configuration, "papers", http)
            try:
                member = await evidence_snapshots.paper(
                    pool, title="Member", sections=["alpha beta"]
                )
                outsider_id = f"W{uuid4().int % 10**12}"
                await pool.execute(
                    """
                    INSERT INTO papers (id, title, publication_year, metadata)
                    VALUES ($1, 'Outsider', 2023,
                            '{"abstract_inverted_index": {"Known": [0], "work": [1]}}')
                    """,
                    outsider_id,
                )
                snapshot_id = await evidence_snapshots.snapshot(pool, [member])
                report = await sync_papers(
                    repository=PaperIndexRepository(pool),
                    papers=papers,
                    embedder=_Embedder(),
                    configuration=configuration,
                    generation=1,
                    snapshot_id=snapshot_id,
                )
                assert report.newly_indexed_count == 1
                indexed = await papers.scroll_payloads(
                    filter_=indexed_paper_filter(1), fields=["paper_id"]
                )
                assert [p["paper_id"] for p in indexed] == [member.paper_id]
                everything = {
                    str(p["paper_id"]): p
                    for p in await papers.scroll_payloads(
                        filter_={}, fields=["paper_id", "catalog_status", "abstract"]
                    )
                }
                assert everything[outsider_id]["catalog_status"] == "metadata_only"
                assert everything[outsider_id]["abstract"] == "Known work"
                assert everything[member.paper_id]["catalog_status"] == "ingested"
            finally:
                await http.delete(f"/collections/{papers.name}")
                await pool.close()

    asyncio.run(exercise())
