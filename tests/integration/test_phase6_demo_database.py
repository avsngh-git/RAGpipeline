"""PostgreSQL coverage for the public demo bundle database files."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID, uuid4

import asyncpg
import pytest

from research_platform.demo.database import (
    DEMO_TABLES,
    EXCLUDED_TABLES,
    DemoExportRefused,
    DemoLoadRefused,
    export_tables,
    load_tables,
)
from research_platform.persistence.migrations import apply_migrations
from research_platform.runs.contracts import ResearchMode, ResearchRequest
from research_platform.runs.repository import RunRepository

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")
DEMO_DATABASE = "research_test_demo"


class _PaperFixture(Protocol):
    paper_id: str
    document_id: UUID
    evidence_ids: tuple[str, ...]


class _SnapshotFactory(Protocol):
    async def paper(
        self,
        pool: asyncpg.Pool,
        *,
        title: str,
        sections: Sequence[str],
        publication_year: int = 2024,
    ) -> _PaperFixture: ...

    async def snapshot(
        self,
        pool: asyncpg.Pool,
        papers: Sequence[_PaperFixture],
        *,
        finalized: bool = True,
    ) -> UUID: ...


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


def test_every_public_table_is_classified() -> None:
    assert TEST_DATABASE_URL is not None
    _assert_test_database()

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        connection = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            rows = await connection.fetch(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """
            )
        finally:
            await connection.close()

        names = {str(row["table_name"]) for row in rows}
        assert names == {table.name for table in DEMO_TABLES} | EXCLUDED_TABLES

    asyncio.run(exercise())


def test_export_refuses_undisplayable_documents(
    evidence_snapshots: _SnapshotFactory, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with _source_database(evidence_snapshots) as (pool, snapshot_id, papers):
            async with pool.acquire() as connection:
                with pytest.raises(DemoExportRefused):
                    await export_tables(
                        connection,
                        snapshot_id=snapshot_id,
                        run_principal="demo",
                        bundle_dir=tmp_path,
                    )

    asyncio.run(exercise())


def test_export_and_load_round_trip(
    evidence_snapshots: _SnapshotFactory, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with _source_database(evidence_snapshots) as (pool, snapshot_id, papers):
            principal = f"demo-{uuid4().hex}"
            other_principal = f"other-{uuid4().hex}"
            async with pool.acquire() as connection:
                document_ids = [paper.document_id for paper in papers]
                await connection.execute(
                    "UPDATE document_permission_evidence SET passage_display_permitted = true "
                    "WHERE document_id = ANY($1::uuid[])",
                    document_ids,
                )
                await connection.execute(
                    "UPDATE document_artifacts SET passage_display_permitted = true "
                    "WHERE document_id = ANY($1::uuid[])",
                    document_ids,
                )
            repository = RunRepository(pool)
            request = ResearchRequest(
                question="Synthetic demo export fixture",
                mode=ResearchMode.QUICK,
                snapshot_id=snapshot_id,
            )
            demo_run_id = await repository.create_run(request, principal=principal)
            other_run_id = await repository.create_run(
                request, principal=other_principal
            )
            async with pool.acquire() as connection:
                await connection.execute(
                    "UPDATE research_runs SET status = 'completed' WHERE id = ANY($1::uuid[])",
                    [demo_run_id, other_run_id],
                )
                exported = await export_tables(
                    connection,
                    snapshot_id=snapshot_id,
                    run_principal=principal,
                    bundle_dir=tmp_path,
                )

            for table in exported:
                path = tmp_path / table.path
                assert path.is_file()
                assert _sha256(path) == table.sha256
            assert (
                next(table.rows for table in exported if table.name == "research_runs")
                == 1
            )

            target_url = await _create_demo_database()
            try:
                target = await asyncpg.connect(target_url)
                try:
                    await load_tables(
                        target,
                        bundle_dir=tmp_path,
                        tables=exported,
                    )
                    assert (
                        await target.fetchval("SELECT count(*) FROM snapshot_items")
                        == 2
                    )
                    expected_chunks = sum(len(paper.evidence_ids) for paper in papers)
                    assert (
                        await target.fetchval("SELECT count(*) FROM chunks")
                        == expected_chunks
                    )
                    assert (
                        await target.fetchval(
                            "SELECT count(*) FROM research_runs WHERE principal = $1",
                            principal,
                        )
                        == 1
                    )
                    assert (
                        await target.fetchval(
                            "SELECT count(*) FROM research_runs WHERE principal = $1",
                            other_principal,
                        )
                        == 0
                    )
                    assert await target.fetchval("SELECT count(*) FROM api_keys") == 0
                    assert (
                        await target.fetchval("SELECT count(*) FROM llm_call_payloads")
                        == 0
                    )
                finally:
                    await target.close()
            finally:
                await _drop_demo_database()

    asyncio.run(exercise())


def test_load_refuses_a_tampered_file(
    evidence_snapshots: _SnapshotFactory, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with _source_database(evidence_snapshots) as (pool, snapshot_id, papers):
            await _allow_display(pool, papers)
            async with pool.acquire() as connection:
                exported = await export_tables(
                    connection,
                    snapshot_id=snapshot_id,
                    run_principal=f"demo-{uuid4().hex}",
                    bundle_dir=tmp_path,
                )
            first = exported[0]
            path = tmp_path / first.path
            content = bytearray(path.read_bytes())
            content[0] ^= 1
            path.write_bytes(content)

            target_url = await _create_demo_database()
            try:
                target = await asyncpg.connect(target_url)
                try:
                    with pytest.raises(DemoLoadRefused):
                        await load_tables(target, bundle_dir=tmp_path, tables=exported)
                    assert await target.fetchval("SELECT count(*) FROM snapshots") == 0
                    assert await target.fetchval("SELECT count(*) FROM papers") == 0
                finally:
                    await target.close()
            finally:
                await _drop_demo_database()

    asyncio.run(exercise())


def test_load_refuses_a_non_empty_target(
    evidence_snapshots: _SnapshotFactory, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with _source_database(evidence_snapshots) as (pool, snapshot_id, papers):
            await _allow_display(pool, papers)
            async with pool.acquire() as connection:
                exported = await export_tables(
                    connection,
                    snapshot_id=snapshot_id,
                    run_principal=f"demo-{uuid4().hex}",
                    bundle_dir=tmp_path,
                )
            target_url = await _create_demo_database()
            try:
                target = await asyncpg.connect(target_url)
                try:
                    await load_tables(target, bundle_dir=tmp_path, tables=exported)
                    with pytest.raises(DemoLoadRefused):
                        await load_tables(target, bundle_dir=tmp_path, tables=exported)
                finally:
                    await target.close()
            finally:
                await _drop_demo_database()

    asyncio.run(exercise())


@asynccontextmanager
async def _source_database(
    evidence_snapshots: _SnapshotFactory,
) -> AsyncIterator[tuple[asyncpg.Pool, UUID, tuple[_PaperFixture, ...]]]:
    assert TEST_DATABASE_URL is not None
    _assert_test_database()
    await apply_migrations(TEST_DATABASE_URL)
    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
    papers = tuple(
        [
            await evidence_snapshots.paper(
                pool,
                title=f"Synthetic phase6 demo fixture {index}",
                sections=["Synthetic demo fixture passage for database export."],
            )
            for index in range(2)
        ]
    )
    snapshot_id = await evidence_snapshots.snapshot(pool, papers)
    try:
        yield pool, snapshot_id, papers
    finally:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "ALTER TABLE snapshot_items DISABLE TRIGGER "
                    "snapshot_items_immutable_after_finalize"
                )
                await connection.execute(
                    "ALTER TABLE snapshots DISABLE TRIGGER "
                    "snapshots_immutable_after_finalize"
                )
                try:
                    await connection.execute(
                        "DELETE FROM research_runs WHERE snapshot_id = $1", snapshot_id
                    )
                    await connection.execute(
                        "DELETE FROM snapshot_item_chunks WHERE snapshot_id = $1",
                        snapshot_id,
                    )
                    await connection.execute(
                        "DELETE FROM snapshot_items WHERE snapshot_id = $1", snapshot_id
                    )
                    await connection.execute(
                        "DELETE FROM snapshot_index_states WHERE snapshot_id = $1",
                        snapshot_id,
                    )
                    await connection.execute(
                        "DELETE FROM index_generations WHERE snapshot_id = $1",
                        snapshot_id,
                    )
                    await connection.execute(
                        "DELETE FROM snapshots WHERE id = $1", snapshot_id
                    )
                    artifact_ids = await connection.fetch(
                        "SELECT artifact_id FROM document_artifacts "
                        "WHERE document_id = ANY($1::uuid[])",
                        [paper.document_id for paper in papers],
                    )
                    await connection.execute(
                        "DELETE FROM papers WHERE id = ANY($1::text[])",
                        [paper.paper_id for paper in papers],
                    )
                    if artifact_ids:
                        await connection.execute(
                            "DELETE FROM artifacts WHERE id = ANY($1::uuid[])",
                            [row["artifact_id"] for row in artifact_ids],
                        )
                finally:
                    await connection.execute(
                        "ALTER TABLE snapshot_items ENABLE TRIGGER "
                        "snapshot_items_immutable_after_finalize"
                    )
                    await connection.execute(
                        "ALTER TABLE snapshots ENABLE TRIGGER "
                        "snapshots_immutable_after_finalize"
                    )
        await pool.close()


async def _allow_display(pool: asyncpg.Pool, papers: Sequence[_PaperFixture]) -> None:
    async with pool.acquire() as connection:
        document_ids = [paper.document_id for paper in papers]
        await connection.execute(
            "UPDATE document_permission_evidence SET passage_display_permitted = true "
            "WHERE document_id = ANY($1::uuid[])",
            document_ids,
        )
        await connection.execute(
            "UPDATE document_artifacts SET passage_display_permitted = true "
            "WHERE document_id = ANY($1::uuid[])",
            document_ids,
        )


async def _create_demo_database() -> str:
    assert TEST_DATABASE_URL is not None
    parsed = urlparse(TEST_DATABASE_URL)
    database_name = parsed.path.removeprefix("/")
    assert database_name == "research_test", (
        "integration tests require the isolated research_test database"
    )
    admin = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {DEMO_DATABASE} WITH (FORCE)")
        await admin.execute(f"CREATE DATABASE {DEMO_DATABASE}")
    finally:
        await admin.close()
    target_url = parsed._replace(path=f"/{DEMO_DATABASE}").geturl()
    try:
        await apply_migrations(target_url)
    except Exception:
        await _drop_demo_database()
        raise
    return target_url


async def _drop_demo_database() -> None:
    assert TEST_DATABASE_URL is not None
    admin = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {DEMO_DATABASE} WITH (FORCE)")
    finally:
        await admin.close()


def _assert_test_database() -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test", (
        "integration tests require the isolated research_test database"
    )


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
