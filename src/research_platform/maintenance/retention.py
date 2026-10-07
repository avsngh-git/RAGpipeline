"""Retention policy queries and report types."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.runs.checkpointing import CHECKPOINT_SCHEMA


@dataclass(frozen=True)
class RetentionPolicy:
    """Age limits for run checkpoints and model-call payloads."""

    completed_checkpoint_days: int = 7
    failed_checkpoint_days: int = 30
    llm_payload_days: int = 90

    def __post_init__(self) -> None:
        for value in (
            self.completed_checkpoint_days,
            self.failed_checkpoint_days,
            self.llm_payload_days,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("retention days must be positive integers")


@dataclass(frozen=True)
class UnpublishedGeneration:
    """A failed or unfinished generation that retention must only report."""

    collection_id: UUID
    configuration_id: str
    generation: int
    state: str
    point_count: int


@dataclass(frozen=True)
class RetentionReport:
    """Counts and identifiers selected or removed by a retention run."""

    dry_run: bool
    checkpoint_runs: tuple[UUID, ...]
    llm_payloads: int
    retired_points: int | None
    unpublished_generations: tuple[UnpublishedGeneration, ...]

    def to_json(self) -> dict[str, object]:
        """Return the stable JSON representation used by the command."""
        return {
            "dry_run": self.dry_run,
            "checkpoint_run_count": len(self.checkpoint_runs),
            "llm_payloads": self.llm_payloads,
            "retired_points": self.retired_points,
            "unpublished_generations": [
                {
                    "collection_id": str(generation.collection_id),
                    "configuration_id": generation.configuration_id,
                    "generation": generation.generation,
                    "state": generation.state,
                    "point_count": generation.point_count,
                }
                for generation in self.unpublished_generations
            ],
        }


async def expired_checkpoint_runs(
    pool: asyncpg.Pool, policy: RetentionPolicy
) -> tuple[UUID, ...]:
    """Return terminal runs past their checkpoint retention age."""
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            f"""
            SELECT r.id FROM research_runs r
            WHERE ((r.status = 'completed' AND r.completed_at < now() - make_interval(days => $1))
                OR (r.status = 'failed' AND r.completed_at < now() - make_interval(days => $2)))
              AND EXISTS (
                  SELECT 1 FROM {CHECKPOINT_SCHEMA}.checkpoints c WHERE c.thread_id = r.id::text
              )
            ORDER BY r.completed_at
            """,
            policy.completed_checkpoint_days,
            policy.failed_checkpoint_days,
        )
    return tuple(row["id"] for row in rows)


async def expired_llm_payloads(pool: asyncpg.Pool, policy: RetentionPolicy) -> int:
    """Count model-call payloads older than the configured retention age."""
    async with pool.acquire() as connection:
        count = await connection.fetchval(
            """
            SELECT count(*) FROM llm_call_payloads
            WHERE created_at < now() - make_interval(days => $1)
            """,
            policy.llm_payload_days,
        )
    return int(count)


async def delete_expired_llm_payloads(
    pool: asyncpg.Pool, policy: RetentionPolicy
) -> int:
    """Delete old payload text and return the number of deleted rows."""
    async with pool.acquire() as connection:
        count = await connection.fetchval(
            """
            WITH deleted AS (
                DELETE FROM llm_call_payloads
                WHERE created_at < now() - make_interval(days => $1)
                RETURNING 1
            )
            SELECT count(*) FROM deleted
            """,
            policy.llm_payload_days,
        )
    return int(count)


async def unpublished_generations(
    pool: asyncpg.Pool,
) -> tuple[UnpublishedGeneration, ...]:
    """List eligible generations above the readable published pointer."""
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT generation.collection_id, generation.configuration_id,
                   generation.generation, generation.state, generation.point_count
            FROM index_generations AS generation
            LEFT JOIN index_generation_pointers AS pointer
              ON pointer.collection_id = generation.collection_id
             AND pointer.configuration_id = generation.configuration_id
            WHERE generation.state IN ('building', 'verified', 'failed')
              AND (pointer.published_generation IS NULL
                   OR generation.generation > pointer.published_generation)
            ORDER BY generation.collection_id, generation.configuration_id,
                     generation.generation
            """
        )
    return tuple(
        UnpublishedGeneration(
            collection_id=row["collection_id"],
            configuration_id=row["configuration_id"],
            generation=row["generation"],
            state=row["state"],
            point_count=row["point_count"],
        )
        for row in rows
    )
