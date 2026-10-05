"""PostgreSQL-backed queue for online ingestion requests."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

IngestionRequester = Literal["run", "api", "terminal"]
IngestionStatus = Literal[
    "pending", "claimed", "succeeded", "partially_succeeded", "failed"
]
IngestionTerminalStatus = Literal["succeeded", "partially_succeeded", "failed"]


@dataclass(frozen=True)
class IngestionRequest:
    """One persisted ingestion request returned by the queue."""

    id: UUID
    collection_id: UUID
    run_id: UUID | None
    requested_by: IngestionRequester
    paper_ids: tuple[str, ...]
    status: IngestionStatus
    attempts: int
    result: Mapping[str, object]


class IngestionQueue:
    """Enqueue and lease ingestion requests using PostgreSQL transactions."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @staticmethod
    async def enqueue(
        connection: asyncpg.Connection,
        *,
        collection_id: UUID,
        run_id: UUID | None,
        requested_by: str,
        paper_ids: Sequence[str],
    ) -> UUID:
        """Insert a request in the caller's transaction and return its identifier."""
        if requested_by not in ("run", "api", "terminal"):
            raise ValueError("requested_by must be run, api, or terminal")
        if not 1 <= len(paper_ids) <= 20:
            raise ValueError("paper_ids must contain between 1 and 20 identifiers")
        if any(not isinstance(paper_id, str) or not paper_id for paper_id in paper_ids):
            raise ValueError("paper_ids must contain non-empty strings")

        request_id = await connection.fetchval(
            """
            INSERT INTO ingestion_requests
                (collection_id, run_id, requested_by, paper_ids)
            VALUES ($1, $2, $3, $4::text[])
            RETURNING id
            """,
            collection_id,
            run_id,
            requested_by,
            list(paper_ids),
        )
        if not isinstance(request_id, UUID):
            raise RuntimeError("PostgreSQL returned an invalid ingestion request ID")
        return request_id

    async def claim_next(
        self, worker_id: str, *, lease_seconds: float = 300
    ) -> IngestionRequest | None:
        """Atomically claim the oldest pending request or reclaim an expired lease."""
        _validate_worker_id(worker_id)
        _validate_lease_seconds(lease_seconds)
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                WITH next_request AS (
                    SELECT id
                    FROM ingestion_requests
                    WHERE status = 'pending'
                       OR (status = 'claimed' AND lease_expires_at < now())
                    ORDER BY created_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE ingestion_requests AS request
                SET status = 'claimed',
                    claimed_by = $1,
                    lease_expires_at = now() + ($2 * interval '1 second'),
                    attempts = request.attempts + 1,
                    updated_at = now()
                FROM next_request
                WHERE request.id = next_request.id
                RETURNING request.id, request.collection_id, request.run_id,
                          request.requested_by, request.paper_ids, request.status,
                          request.attempts, request.result
                """,
                worker_id,
                lease_seconds,
            )
        return _request_from_row(row) if row is not None else None

    async def heartbeat(
        self, request_id: UUID, worker_id: str, *, lease_seconds: float = 300
    ) -> bool:
        """Extend the active worker's lease, returning false for a stale owner."""
        _validate_worker_id(worker_id)
        _validate_lease_seconds(lease_seconds)
        async with self._pool.acquire() as connection:
            renewed = await connection.fetchval(
                """
                UPDATE ingestion_requests
                SET lease_expires_at = now() + ($3 * interval '1 second'),
                    updated_at = now()
                WHERE id = $1
                  AND status = 'claimed'
                  AND claimed_by = $2
                  AND lease_expires_at > now()
                RETURNING true
                """,
                request_id,
                worker_id,
                lease_seconds,
            )
        return renewed is True

    async def complete(
        self,
        request_id: UUID,
        worker_id: str,
        *,
        status: IngestionTerminalStatus,
        result: Mapping[str, object],
    ) -> None:
        """Complete a request only while this worker still owns its lease."""
        _validate_worker_id(worker_id)
        if status not in ("succeeded", "partially_succeeded", "failed"):
            raise ValueError("status must be a terminal ingestion status")
        serialized_result = json.dumps(dict(result), allow_nan=False)
        async with self._pool.acquire() as connection:
            completed = await connection.fetchval(
                """
                UPDATE ingestion_requests
                SET status = $3,
                    claimed_by = NULL,
                    lease_expires_at = NULL,
                    result = $4::jsonb,
                    updated_at = now()
                WHERE id = $1 AND status = 'claimed' AND claimed_by = $2
                RETURNING true
                """,
                request_id,
                worker_id,
                status,
                serialized_result,
            )
        if completed is not True:
            raise RuntimeError("worker no longer owns the ingestion request")

    async def get(self, request_id: UUID) -> IngestionRequest:
        """Load a request by its stable identifier."""
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT id, collection_id, run_id, requested_by, paper_ids, status,
                       attempts, result
                FROM ingestion_requests
                WHERE id = $1
                """,
                request_id,
            )
        if row is None:
            raise KeyError(f"ingestion request {request_id} does not exist")
        return _request_from_row(row)


def _request_from_row(row: asyncpg.Record) -> IngestionRequest:
    result_value = row["result"]
    if isinstance(result_value, str):
        result_value = json.loads(result_value)
    if not isinstance(result_value, Mapping):
        raise RuntimeError("ingestion request result is not a JSON object")
    return IngestionRequest(
        id=row["id"],
        collection_id=row["collection_id"],
        run_id=row["run_id"],
        requested_by=row["requested_by"],
        paper_ids=tuple(row["paper_ids"]),
        status=row["status"],
        attempts=row["attempts"],
        result=dict(result_value),
    )


def _validate_worker_id(worker_id: str) -> None:
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ValueError("worker_id must be a non-empty string")


def _validate_lease_seconds(lease_seconds: float) -> None:
    if (
        isinstance(lease_seconds, bool)
        or not isinstance(lease_seconds, (int, float))
        or not math.isfinite(lease_seconds)
        or lease_seconds <= 0
    ):
        raise ValueError("lease_seconds must be a finite positive number")
