"""Live PostgreSQL and Qdrant coverage for building generation passages (P35-06)."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Awaitable, Callable, Sequence
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
    generation_filter,
)
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.indexing import IndexConfiguration
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
        return [(1.0, float(len(text) % 7)) for text in texts]


class Context:
    def __init__(
        self,
        pool: asyncpg.Pool,
        http: httpx.AsyncClient,
        factory: object,
    ) -> None:
        suffix = uuid4().hex[:12]
        self.pool = pool
        self.factory = factory
        self.registry = GenerationRegistry(pool)
        self.configuration = GenerationIndexConfiguration(
            passages_collection=f"phase35-build-passages-{suffix}",
            papers_collection=f"phase35-build-papers-{suffix}",
            embedding_model="integration-fixture",
            embedding_revision="v1",
            preprocessing_revision="raw-text-v1",
            vector_size=2,
            distance="Cosine",
            batch_size=2,
            maximum_input_tokens=32,
        )
        self.passages = GenerationQdrantCollection(self.configuration, "passages", http)

    async def build(self, collection_id: object, snapshot_id: object):
        return await build_generation_passages(
            registry=self.registry,
            inputs=GenerationInputRepository(self.pool),
            passages=self.passages,
            embedder=_Embedder(),
            configuration=self.configuration,
            collection_id=collection_id,  # type: ignore[arg-type]
            snapshot_id=snapshot_id,  # type: ignore[arg-type]
        )


def _with_context(
    factory: object, operation: Callable[[Context], Awaitable[None]]
) -> None:
    assert TEST_DATABASE_URL is not None and TEST_QDRANT_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=3)
        async with httpx.AsyncClient(base_url=TEST_QDRANT_URL, timeout=30) as http:
            context = Context(pool, http, factory)
            try:
                await operation(context)
            finally:
                await http.delete(f"/collections/{context.passages.name}")
                await pool.close()

    asyncio.run(exercise())


def test_build_generation_one_counts_and_payloads(evidence_snapshots) -> None:
    async def exercise(context: Context) -> None:
        first = await evidence_snapshots.paper(
            context.pool, title="First", sections=["alpha beta", "gamma delta"]
        )
        second = await evidence_snapshots.paper(
            context.pool, title="Second", sections=["epsilon zeta"]
        )
        snapshot_id = await evidence_snapshots.snapshot(context.pool, [first, second])
        collection_id = await context.registry.ensure_collection(
            f"phase35-build-{uuid4().hex}"
        )
        report = await context.build(collection_id, snapshot_id)

        assert report.generation == 1
        assert report.added_count == 3 == report.embedded_count
        assert await context.passages.count(generation_filter(1)) == 3
        payloads = await context.passages.scroll_payloads(
            filter_=generation_filter(1),
            fields=[
                "evidence_id",
                "text",
                "text_sha256",
                "source_spans",
                "paper_title",
            ],
        )
        texts = {**first.texts, **second.texts}
        for payload in payloads:
            text = texts[str(payload["evidence_id"])]
            assert payload["text"] == text
            assert payload["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
            assert payload["source_spans"]
        assert {p["paper_title"] for p in payloads} == {"First", "Second"}
        record = await context.registry.get(
            collection_id, context.configuration.configuration_id, 1
        )
        assert record.state == "building"
        assert record.manifest_sha256 == report.manifest_sha256

    _with_context(evidence_snapshots, exercise)


def test_build_generation_two_retires_removed_chunk(evidence_snapshots) -> None:
    async def exercise(context: Context) -> None:
        kept = await evidence_snapshots.paper(
            context.pool, title="Kept", sections=["alpha beta"]
        )
        removed = await evidence_snapshots.paper(
            context.pool, title="Removed", sections=["gamma delta"]
        )
        added = await evidence_snapshots.paper(
            context.pool, title="Added", sections=["epsilon zeta"]
        )
        collection_id = await context.registry.ensure_collection(
            f"phase35-build-{uuid4().hex}"
        )
        await context.build(
            collection_id,
            await evidence_snapshots.snapshot(context.pool, [kept, removed]),
        )
        report = await context.build(
            collection_id,
            await evidence_snapshots.snapshot(context.pool, [kept, added]),
        )

        assert (report.generation, report.added_count, report.retired_count) == (
            2,
            1,
            1,
        )

        async def visible(generation: int) -> set[str]:
            payloads = await context.passages.scroll_payloads(
                filter_=generation_filter(generation), fields=["evidence_id"]
            )
            return {str(p["evidence_id"]) for p in payloads}

        assert await visible(1) == {*kept.evidence_ids, *removed.evidence_ids}
        assert await visible(2) == {*kept.evidence_ids, *added.evidence_ids}

    _with_context(evidence_snapshots, exercise)
