"""PostgreSQL coverage for the append-only lexical vocabulary (P35-11)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import pytest

from research_platform.persistence.migrations import apply_migrations
from research_platform.search.sparse_lexical import VocabularyRepository

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def _with_vocabulary(
    operation: Callable[[asyncpg.Pool, VocabularyRepository, str], Awaitable[None]],
) -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=4)
        repository = VocabularyRepository(pool)
        vocabulary_id = f"test-{uuid4().hex}"
        try:
            await repository.ensure_vocabulary(
                vocabulary_id, analyzer="scientific-en", analyzer_revision="v1"
            )
            await operation(pool, repository, vocabulary_id)
        finally:
            await pool.close()

    asyncio.run(exercise())


def test_ids_are_stable_and_append_only() -> None:
    async def exercise(
        _pool: asyncpg.Pool, repository: VocabularyRepository, vocabulary_id: str
    ) -> None:
        first = await repository.ensure_terms(vocabulary_id, ["gpt-3.5", "bm25"])
        assert first == {"bm25": 0, "gpt-3.5": 1}
        second = await repository.ensure_terms(vocabulary_id, ["ndcg@10", "bm25"])
        assert second == {"bm25": 0, "ndcg@10": 2}
        assert await repository.lookup(vocabulary_id, ["bm25", "missing"]) == {
            "bm25": 0
        }
        with pytest.raises(ValueError, match="different analyzer"):
            await repository.ensure_vocabulary(
                vocabulary_id, analyzer="other", analyzer_revision="v1"
            )

    _with_vocabulary(exercise)


def test_concurrent_ensure_terms_assign_unique_ids() -> None:
    async def exercise(
        _pool: asyncpg.Pool, repository: VocabularyRepository, vocabulary_id: str
    ) -> None:
        batches = [[f"t{i}", f"t{i + 1}", "shared"] for i in range(0, 20, 2)]
        results = await asyncio.gather(
            *(repository.ensure_terms(vocabulary_id, batch) for batch in batches)
        )
        merged: dict[str, int] = {}
        for result in results:
            for term, term_id in result.items():
                assert merged.setdefault(term, term_id) == term_id
        assert sorted(merged.values()) == list(range(len(merged)))

    _with_vocabulary(exercise)


def test_update_and_delete_are_rejected() -> None:
    async def exercise(
        pool: asyncpg.Pool, repository: VocabularyRepository, vocabulary_id: str
    ) -> None:
        await repository.ensure_terms(vocabulary_id, ["bm25"])
        async with pool.acquire() as connection:
            with pytest.raises(asyncpg.RaiseError, match="append-only"):
                await connection.execute(
                    "UPDATE lexical_terms SET term_id = 9 WHERE vocabulary_id = $1",
                    vocabulary_id,
                )
            with pytest.raises(asyncpg.RaiseError, match="append-only"):
                await connection.execute(
                    "DELETE FROM lexical_terms WHERE vocabulary_id = $1", vocabulary_id
                )

    _with_vocabulary(exercise)
