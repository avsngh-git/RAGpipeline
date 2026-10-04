"""PostgreSQL coverage for the index generation registry (ADR-0023)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse
from uuid import UUID, uuid4

import asyncpg
import pytest

from research_platform.ingestion.generation_registry import (
    GenerationRegistry,
    PublicationConflict,
)
from research_platform.persistence.migrations import apply_migrations

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")
MANIFEST = "a" * 64

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


class Fixture:
    def __init__(
        self, pool: asyncpg.Pool, registry: GenerationRegistry, collection_id: UUID
    ) -> None:
        self.pool = pool
        self.registry = registry
        self.collection_id = collection_id
        self.configuration_id = f"sha256:{uuid4().hex}{uuid4().hex}"

    async def snapshot(self, *, finalized: bool = True) -> UUID:
        snapshot_id = uuid4()
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO snapshots (id, name, configuration_id, configuration,
                                       code_revision)
                VALUES ($1, $2, 'test-config', '{}'::jsonb, 'test-revision')
                """,
                snapshot_id,
                f"generation-registry-{snapshot_id}",
            )
            if finalized:
                await connection.execute(
                    """
                    UPDATE snapshots
                    SET status = 'finalized', finalized_at = now(),
                        finalized_by = 'integration-test'
                    WHERE id = $1
                    """,
                    snapshot_id,
                )
        return snapshot_id

    async def register(self) -> int:
        record = await self.registry.register_generation(
            collection_id=self.collection_id,
            configuration_id=self.configuration_id,
            snapshot_id=await self.snapshot(),
            manifest_sha256=MANIFEST,
        )
        return record.generation

    async def verify(self, generation: int) -> None:
        await self.registry.mark_verified(
            self.collection_id,
            self.configuration_id,
            generation,
            point_count=3,
            details={"checked": True},
        )


def test_first_generation_is_one_without_parent() -> None:
    async def exercise(fixture: Fixture) -> None:
        record = await fixture.registry.register_generation(
            collection_id=fixture.collection_id,
            configuration_id=fixture.configuration_id,
            snapshot_id=await fixture.snapshot(),
            manifest_sha256=MANIFEST,
        )
        assert record.generation == 1
        assert record.parent_generation is None
        assert record.state == "building"
        assert record.point_count == 0

    _with_registry(exercise)


def test_second_generation_links_parent() -> None:
    async def exercise(fixture: Fixture) -> None:
        await fixture.register()
        second = await fixture.registry.get(
            fixture.collection_id, fixture.configuration_id, await fixture.register()
        )
        assert second.generation == 2
        assert second.parent_generation == 1
        latest = await fixture.registry.latest(
            fixture.collection_id, fixture.configuration_id
        )
        assert latest == second

    _with_registry(exercise)


def test_draft_snapshot_is_rejected() -> None:
    async def exercise(fixture: Fixture) -> None:
        with pytest.raises(ValueError, match="finalized snapshot"):
            await fixture.registry.register_generation(
                collection_id=fixture.collection_id,
                configuration_id=fixture.configuration_id,
                snapshot_id=await fixture.snapshot(finalized=False),
                manifest_sha256=MANIFEST,
            )

    _with_registry(exercise)


def test_publish_requires_verified_state() -> None:
    async def exercise(fixture: Fixture) -> None:
        generation = await fixture.register()
        with pytest.raises(PublicationConflict, match="building to published"):
            await fixture.registry.publish(
                fixture.collection_id,
                fixture.configuration_id,
                generation,
                expected_predecessor=None,
            )
        assert (
            await fixture.registry.published(
                fixture.collection_id, fixture.configuration_id
            )
            is None
        )

    _with_registry(exercise)


def test_publish_with_wrong_predecessor_changes_nothing() -> None:
    async def exercise(fixture: Fixture) -> None:
        generation = await fixture.register()
        await fixture.verify(generation)
        with pytest.raises(PublicationConflict, match="expected predecessor"):
            await fixture.registry.publish(
                fixture.collection_id,
                fixture.configuration_id,
                generation,
                expected_predecessor=4,
            )
        record = await fixture.registry.get(
            fixture.collection_id, fixture.configuration_id, generation
        )
        assert record.state == "verified"
        assert (
            await fixture.registry.published(
                fixture.collection_id, fixture.configuration_id
            )
            is None
        )

    _with_registry(exercise)


def test_publish_moves_pointer_and_published_returns_it() -> None:
    async def exercise(fixture: Fixture) -> None:
        first = await fixture.register()
        await fixture.verify(first)
        await fixture.registry.publish(
            fixture.collection_id,
            fixture.configuration_id,
            first,
            expected_predecessor=None,
        )
        second = await fixture.register()
        await fixture.verify(second)
        await fixture.registry.publish(
            fixture.collection_id,
            fixture.configuration_id,
            second,
            expected_predecessor=first,
        )
        published = await fixture.registry.published(
            fixture.collection_id, fixture.configuration_id
        )
        assert published is not None
        assert published.generation == second
        assert published.state == "published"
        assert published.point_count == 3
        assert published.details == {"checked": True}
        by_snapshot = await fixture.registry.by_snapshot(
            fixture.configuration_id, published.snapshot_id
        )
        assert by_snapshot == published

    _with_registry(exercise)


def test_concurrent_publish_with_same_predecessor_has_one_winner() -> None:
    async def exercise(fixture: Fixture) -> None:
        first = await fixture.register()
        second = await fixture.register()
        await fixture.verify(first)
        await fixture.verify(second)
        results = await asyncio.gather(
            *(
                fixture.registry.publish(
                    fixture.collection_id,
                    fixture.configuration_id,
                    generation,
                    expected_predecessor=None,
                )
                for generation in (first, second)
            ),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 1
        assert sum(isinstance(result, PublicationConflict) for result in results) == 1

    _with_registry(exercise)


def test_mark_failed_records_reason() -> None:
    async def exercise(fixture: Fixture) -> None:
        generation = await fixture.register()
        await fixture.registry.mark_failed(
            fixture.collection_id,
            fixture.configuration_id,
            generation,
            reason="verification_failed",
        )
        record = await fixture.registry.get(
            fixture.collection_id, fixture.configuration_id, generation
        )
        assert record.state == "failed"
        assert record.details["failure_reason"] == "verification_failed"
        with pytest.raises(PublicationConflict):
            await fixture.verify(generation)

    _with_registry(exercise)


def test_ensure_collection_is_idempotent() -> None:
    async def exercise(fixture: Fixture) -> None:
        name = f"generation-registry-{uuid4().hex}"
        first = await fixture.registry.ensure_collection(name)
        second = await fixture.registry.ensure_collection(name)
        assert first == second
        async with fixture.pool.acquire() as connection:
            await connection.execute("DELETE FROM collections WHERE id = $1", first)

    _with_registry(exercise)


def _with_registry(operation: Callable[[Fixture], Awaitable[None]]) -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=4)
        registry = GenerationRegistry(pool)
        collection_id = await registry.ensure_collection(
            f"generation-registry-{uuid4().hex}"
        )
        fixture = Fixture(pool, registry, collection_id)
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    """
                    INSERT INTO index_configurations (configuration_id, configuration)
                    VALUES ($1, '{}'::jsonb)
                    """,
                    fixture.configuration_id,
                )
            await operation(fixture)
        finally:
            # Finalized snapshots are immutable by design and remain in the disposable
            # test database; registry rows and the collection are removed.
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM index_generation_pointers WHERE collection_id = $1",
                    collection_id,
                )
                await connection.execute(
                    "DELETE FROM index_generations WHERE collection_id = $1",
                    collection_id,
                )
                await connection.execute(
                    "DELETE FROM index_configurations WHERE configuration_id = $1",
                    fixture.configuration_id,
                )
                await connection.execute(
                    "DELETE FROM collections WHERE id = $1", collection_id
                )
            await pool.close()

    asyncio.run(exercise())
