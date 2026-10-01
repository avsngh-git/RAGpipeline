"""PostgreSQL persistence for LangGraph run checkpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

CHECKPOINT_SCHEMA: Final = "langgraph"

_CHECKPOINT_TYPES: Final = (
    ("research_platform.api.schemas.search", "SearchFiltersModel"),
    ("research_platform.llm.types", "CallKind"),
    ("research_platform.llm.types", "ModelIdentity"),
    ("research_platform.runs.contracts", "AnswerOutcome"),
    ("research_platform.runs.contracts", "ClaimResult"),
    ("research_platform.runs.contracts", "EvidenceCitation"),
    ("research_platform.runs.contracts", "FailureCategory"),
    ("research_platform.runs.contracts", "PaperSummary"),
    ("research_platform.runs.contracts", "ResearchFilters"),
    ("research_platform.runs.contracts", "ResearchMode"),
    ("research_platform.runs.contracts", "ResearchRequest"),
    ("research_platform.runs.contracts", "ResearchRunView"),
    ("research_platform.runs.contracts", "RunBudgets"),
    ("research_platform.runs.contracts", "RunProvenance"),
    ("research_platform.runs.contracts", "RunStatus"),
    ("research_platform.runs.contracts", "RunUsage"),
    ("research_platform.runs.contracts", "SupportLabel"),
)


def _serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_TYPES)


def checkpoint_conninfo(database_url: str) -> str:
    """Return psycopg conninfo restricted to the checkpoint schema."""
    return make_conninfo(database_url, options=f"-c search_path={CHECKPOINT_SCHEMA}")


@asynccontextmanager
async def open_checkpointer(
    database_url: str, *, max_size: int = 4
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open a pooled async checkpointer and close its pool on exit."""
    if max_size < 1:
        raise ValueError("max_size must be positive")
    pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] = AsyncConnectionPool(
        conninfo=checkpoint_conninfo(database_url),
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
        min_size=1,
        max_size=max_size,
        open=False,
    )
    async with pool:
        yield AsyncPostgresSaver(pool, serde=_serializer())


async def setup_checkpoints(database_url: str) -> None:
    """Create the isolated schema and initialize LangGraph's checkpoint tables."""
    async with await AsyncConnection.connect(
        checkpoint_conninfo(database_url),
        autocommit=True,
        row_factory=dict_row,
        prepare_threshold=0,
    ) as connection:
        await connection.execute(f"CREATE SCHEMA IF NOT EXISTS {CHECKPOINT_SCHEMA}")
    async with open_checkpointer(database_url, max_size=1) as saver:
        await saver.setup()


async def delete_run_checkpoints(saver: AsyncPostgresSaver, run_id: UUID) -> None:
    """Delete every checkpoint and pending write for a run thread."""
    await saver.adelete_thread(str(run_id))


def thread_config(run_id: UUID) -> dict[str, dict[str, str]]:
    """Return LangGraph's thread configuration for a research run."""
    return {"configurable": {"thread_id": str(run_id)}}
