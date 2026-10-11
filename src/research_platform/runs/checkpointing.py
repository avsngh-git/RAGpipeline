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

# Exactly the pydantic models and enums reachable from ResearchState
# (tests/test_checkpoint_allowlist.py checks this). LangGraph's msgpack serializer
# rebuilds only allow-listed types; any other type is logged and returned as raw data
# (CVE-2026-28277, GHSA-g48c-2wqr-h844).
_CHECKPOINT_TYPES: Final = (
    ("research_platform.agents.answering", "VerifiedAnswer"),
    ("research_platform.agents.evidence", "EvidenceRef"),
    ("research_platform.agents.evidence", "EvidenceRegistry"),
    ("research_platform.runs.contracts", "AnswerOutcome"),
    ("research_platform.runs.contracts", "ClaimResult"),
    ("research_platform.runs.contracts", "ClaimVerdict"),
    ("research_platform.runs.contracts", "DraftClaimOutcome"),
    ("research_platform.runs.contracts", "EvidenceCitation"),
    ("research_platform.runs.contracts", "SupportLabel"),
    ("research_platform.runs.contracts", "SynthesisSummary"),
    ("research_platform.tools.research_tools", "ToolLedger"),
)


def checkpoint_serializer() -> JsonPlusSerializer:
    """The serializer every checkpointer uses, production and scripted alike."""
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
        yield AsyncPostgresSaver(pool, serde=checkpoint_serializer())


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
