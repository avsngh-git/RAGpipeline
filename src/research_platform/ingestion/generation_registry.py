"""PostgreSQL registry of index generations and their published pointer (ADR-0023)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

GenerationState = Literal["building", "verified", "published", "failed"]
_STATES = frozenset({"building", "verified", "published", "failed"})
_SELECT = """
SELECT collection_id, configuration_id, generation, snapshot_id, parent_generation,
       manifest_sha256, state, point_count, details
FROM index_generations
"""


@dataclass(frozen=True)
class GenerationRecord:
    """One generation of a collection under one index configuration."""

    collection_id: UUID
    configuration_id: str
    generation: int
    snapshot_id: UUID
    parent_generation: int | None
    manifest_sha256: str
    state: GenerationState
    point_count: int
    details: Mapping[str, object]


class GenerationNotFound(LookupError):
    """The requested generation does not exist."""


class PublicationConflict(RuntimeError):
    """A state change or publication does not match the registry's current state."""


class GenerationRegistry:
    """Register, verify, fail and publish generations with short transactions."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_collection(
        self, name: str, *, description: str | None = None
    ) -> UUID:
        """Return the collection ID for ``name``, creating the row when absent."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("collection name must be a non-empty string")
        async with self._pool.acquire() as connection:
            collection_id = await connection.fetchval(
                """
                INSERT INTO collections (name, description) VALUES ($1, $2)
                ON CONFLICT (name) DO NOTHING
                RETURNING id
                """,
                name.strip(),
                description,
            )
            if collection_id is None:
                collection_id = await connection.fetchval(
                    "SELECT id FROM collections WHERE name = $1", name.strip()
                )
        return cast(UUID, collection_id)

    async def register_generation(
        self,
        *,
        collection_id: UUID,
        configuration_id: str,
        snapshot_id: UUID,
        manifest_sha256: str,
    ) -> GenerationRecord:
        """Register the next generation in ``building`` state for a finalized snapshot."""
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await _lock(connection, collection_id, configuration_id)
                status = await connection.fetchval(
                    "SELECT status FROM snapshots WHERE id = $1", snapshot_id
                )
                if status is None:
                    raise ValueError("snapshot does not exist")
                if status != "finalized":
                    raise ValueError("a generation requires a finalized snapshot")
                previous = await connection.fetchval(
                    """
                    SELECT max(generation) FROM index_generations
                    WHERE collection_id = $1 AND configuration_id = $2
                    """,
                    collection_id,
                    configuration_id,
                )
                generation = 1 if previous is None else int(previous) + 1
                row = await connection.fetchrow(
                    """
                    INSERT INTO index_generations
                        (collection_id, configuration_id, generation, snapshot_id,
                         parent_generation, manifest_sha256, state)
                    VALUES ($1, $2, $3, $4, $5, $6, 'building')
                    RETURNING collection_id, configuration_id, generation, snapshot_id,
                              parent_generation, manifest_sha256, state, point_count,
                              details
                    """,
                    collection_id,
                    configuration_id,
                    generation,
                    snapshot_id,
                    previous,
                    manifest_sha256,
                )
        return _record(row)

    async def mark_verified(
        self,
        collection_id: UUID,
        configuration_id: str,
        generation: int,
        *,
        point_count: int,
        details: Mapping[str, object],
    ) -> None:
        """Move a generation from ``building`` to ``verified``."""
        if point_count < 0:
            raise ValueError("point_count must not be negative")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._transition(
                    connection,
                    collection_id,
                    configuration_id,
                    generation,
                    allowed=frozenset({"building"}),
                    state="verified",
                )
                await connection.execute(
                    """
                    UPDATE index_generations
                    SET point_count = $4, details = $5::jsonb
                    WHERE collection_id = $1 AND configuration_id = $2
                      AND generation = $3
                    """,
                    collection_id,
                    configuration_id,
                    generation,
                    point_count,
                    json.dumps(dict(details), sort_keys=True),
                )

    async def mark_failed(
        self,
        collection_id: UUID,
        configuration_id: str,
        generation: int,
        *,
        reason: str,
    ) -> None:
        """Move a ``building`` or ``verified`` generation to ``failed``."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._transition(
                    connection,
                    collection_id,
                    configuration_id,
                    generation,
                    allowed=frozenset({"building", "verified"}),
                    state="failed",
                )
                await connection.execute(
                    """
                    UPDATE index_generations
                    SET details = details || jsonb_build_object('failure_reason', $4::text)
                    WHERE collection_id = $1 AND configuration_id = $2
                      AND generation = $3
                    """,
                    collection_id,
                    configuration_id,
                    generation,
                    reason.strip(),
                )

    async def publish(
        self,
        collection_id: UUID,
        configuration_id: str,
        generation: int,
        *,
        expected_predecessor: int | None,
    ) -> None:
        """Publish a verified generation if the pointer still names the predecessor."""
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await _lock(connection, collection_id, configuration_id)
                current = await connection.fetchval(
                    """
                    SELECT published_generation FROM index_generation_pointers
                    WHERE collection_id = $1 AND configuration_id = $2
                    FOR UPDATE
                    """,
                    collection_id,
                    configuration_id,
                )
                if current != expected_predecessor:
                    raise PublicationConflict(
                        "the published generation differs from the expected predecessor"
                    )
                await self._transition(
                    connection,
                    collection_id,
                    configuration_id,
                    generation,
                    allowed=frozenset({"verified"}),
                    state="published",
                )
                await connection.execute(
                    """
                    INSERT INTO index_generation_pointers
                        (collection_id, configuration_id, published_generation)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (collection_id, configuration_id)
                    DO UPDATE SET published_generation = EXCLUDED.published_generation,
                                  updated_at = now()
                    """,
                    collection_id,
                    configuration_id,
                    generation,
                )

    async def published(
        self, collection_id: UUID, configuration_id: str
    ) -> GenerationRecord | None:
        """Return the generation the pointer names, or ``None`` before publication."""
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                _SELECT
                + """
                WHERE (collection_id, configuration_id, generation) = (
                    SELECT collection_id, configuration_id, published_generation
                    FROM index_generation_pointers
                    WHERE collection_id = $1 AND configuration_id = $2)
                """,
                collection_id,
                configuration_id,
            )
        return None if row is None else _record(row)

    async def get(
        self, collection_id: UUID, configuration_id: str, generation: int
    ) -> GenerationRecord:
        """Return one generation or raise ``GenerationNotFound``."""
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                _SELECT
                + """
                WHERE collection_id = $1 AND configuration_id = $2 AND generation = $3
                """,
                collection_id,
                configuration_id,
                generation,
            )
        if row is None:
            raise GenerationNotFound("generation does not exist")
        return _record(row)

    async def by_snapshot(
        self, configuration_id: str, snapshot_id: UUID
    ) -> GenerationRecord | None:
        """Return the generation built from ``snapshot_id`` under a configuration."""
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                _SELECT + " WHERE configuration_id = $1 AND snapshot_id = $2",
                configuration_id,
                snapshot_id,
            )
        return None if row is None else _record(row)

    async def latest(
        self, collection_id: UUID, configuration_id: str
    ) -> GenerationRecord | None:
        """Return the highest-numbered generation in any state."""
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                _SELECT
                + """
                WHERE collection_id = $1 AND configuration_id = $2
                ORDER BY generation DESC LIMIT 1
                """,
                collection_id,
                configuration_id,
            )
        return None if row is None else _record(row)

    async def _transition(
        self,
        connection: asyncpg.Connection,
        collection_id: UUID,
        configuration_id: str,
        generation: int,
        *,
        allowed: frozenset[str],
        state: GenerationState,
    ) -> None:
        current = await connection.fetchval(
            """
            SELECT state FROM index_generations
            WHERE collection_id = $1 AND configuration_id = $2 AND generation = $3
            FOR UPDATE
            """,
            collection_id,
            configuration_id,
            generation,
        )
        if current is None:
            raise GenerationNotFound("generation does not exist")
        if current not in allowed:
            raise PublicationConflict(
                f"cannot move generation {generation} from {current} to {state}"
            )
        await connection.execute(
            """
            UPDATE index_generations SET state = $4, updated_at = now()
            WHERE collection_id = $1 AND configuration_id = $2 AND generation = $3
            """,
            collection_id,
            configuration_id,
            generation,
            state,
        )


async def _lock(
    connection: asyncpg.Connection, collection_id: UUID, configuration_id: str
) -> None:
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        f"generation:{collection_id}:{configuration_id}",
    )


def _record(row: Mapping[str, object]) -> GenerationRecord:
    state = row["state"]
    if state not in _STATES:
        raise RuntimeError("generation has an unknown state")
    details = row["details"]
    if isinstance(details, str):
        details = json.loads(details)
    if not isinstance(details, Mapping):
        raise RuntimeError("generation details are not a JSON object")
    parent = row["parent_generation"]
    return GenerationRecord(
        collection_id=cast(UUID, row["collection_id"]),
        configuration_id=cast(str, row["configuration_id"]),
        generation=cast(int, row["generation"]),
        snapshot_id=cast(UUID, row["snapshot_id"]),
        parent_generation=None if parent is None else cast(int, parent),
        manifest_sha256=cast(str, row["manifest_sha256"]),
        state=cast(GenerationState, state),
        point_count=cast(int, row["point_count"]),
        details=dict(details),
    )
