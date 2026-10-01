"""PostgreSQL integration checks for durable LangGraph checkpoints."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import TypedDict
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import pytest
from langgraph.graph import END, START, StateGraph

from research_platform.api.schemas.search import SearchFiltersModel
from research_platform.persistence.migrations import apply_migrations
from research_platform.runs.checkpointing import (
    delete_run_checkpoints,
    open_checkpointer,
    thread_config,
)

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="requires the dedicated disposable PostgreSQL service",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def remove_checkpoint_test_schema() -> Iterator[None]:
    """Restore the disposable database for integration modules that follow."""
    yield
    if not TEST_DATABASE_URL:
        return

    async def cleanup() -> None:
        connection = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            await connection.execute("DROP SCHEMA IF EXISTS langgraph CASCADE")
            await connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
            await connection.execute("CREATE SCHEMA public")
        finally:
            await connection.close()

    asyncio.run(cleanup())


class _GraphState(TypedDict, total=False):
    filters: SearchFiltersModel
    finished: bool


def test_setup_creates_tables_in_langgraph_schema_only() -> None:
    assert TEST_DATABASE_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        connection = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            tables = await connection.fetch(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_name LIKE 'checkpoint%'
                   OR table_name = 'migrations'
                """
            )
            checkpoint_tables = {
                row["table_name"]
                for row in tables
                if row["table_schema"] == "langgraph"
            }
            public_checkpoint_tables = {
                row["table_name"] for row in tables if row["table_schema"] == "public"
            }
            assert {"checkpoints", "checkpoint_blobs", "checkpoint_writes"} <= (
                checkpoint_tables
            )
            assert not public_checkpoint_tables
        finally:
            await connection.close()

    asyncio.run(exercise())


def test_setup_is_idempotent() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        await apply_migrations(TEST_DATABASE_URL)

    asyncio.run(exercise())


def test_tiny_graph_checkpoints_and_resumes() -> None:
    assert TEST_DATABASE_URL is not None
    run_id = uuid4()
    first_calls = 0
    second_calls = 0

    async def first_node(_state: _GraphState) -> _GraphState:
        nonlocal first_calls
        first_calls += 1
        return {"filters": SearchFiltersModel(year_from=2022)}

    async def second_node(_state: _GraphState) -> _GraphState:
        nonlocal second_calls
        second_calls += 1
        if second_calls == 1:
            raise RuntimeError("simulated interruption")
        return {"finished": True}

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        async with open_checkpointer(TEST_DATABASE_URL) as saver:
            graph_builder = StateGraph(_GraphState)
            graph_builder.add_node("first", first_node)
            graph_builder.add_node("second", second_node)
            graph_builder.add_edge(START, "first")
            graph_builder.add_edge("first", "second")
            graph_builder.add_edge("second", END)
            graph = graph_builder.compile(checkpointer=saver)
            config = thread_config(run_id)

            with pytest.raises(RuntimeError, match="simulated interruption"):
                await graph.ainvoke({}, config)

            result = await graph.ainvoke(None, config)

            assert result["finished"] is True
            assert result["filters"] == SearchFiltersModel(year_from=2022)
            assert first_calls == 1
            assert second_calls == 2

    asyncio.run(exercise())


def test_strict_msgpack_round_trip_of_project_model() -> None:
    assert TEST_DATABASE_URL is not None

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        async with open_checkpointer(TEST_DATABASE_URL) as saver:
            model = SearchFiltersModel(year_from=2022)
            type_name, payload = saver.serde.dumps_typed(model)

            assert saver.serde.loads_typed((type_name, payload)) == model

    asyncio.run(exercise())


def test_delete_run_checkpoints_removes_thread() -> None:
    assert TEST_DATABASE_URL is not None
    run_id = uuid4()

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        async with open_checkpointer(TEST_DATABASE_URL) as saver:
            config = thread_config(run_id)
            config["configurable"]["checkpoint_ns"] = ""
            await saver.aput(
                config,
                {
                    "v": 4,
                    "id": "checkpoint-1",
                    "ts": "2026-10-01T00:00:00Z",
                    "channel_values": {},
                    "channel_versions": {},
                    "versions_seen": {},
                },
                {"source": "loop", "step": 1, "parents": {}},
                {},
            )

            await delete_run_checkpoints(saver, run_id)

            assert await saver.aget_tuple(config) is None

    asyncio.run(exercise())
