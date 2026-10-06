"""PostgreSQL advisory lock for work that shares the research GPU."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg  # type: ignore[import-untyped]


@asynccontextmanager
async def gpu_lock(pool: asyncpg.Pool) -> AsyncIterator[None]:
    """Hold the process-wide research GPU lock on a dedicated database session."""
    async with pool.acquire() as connection:
        try:
            await connection.fetchval(
                "SELECT pg_advisory_lock(hashtextextended('research-gpu', 0))"
            )
        except BaseException:
            connection.terminate()
            raise
        try:
            yield
        finally:
            try:
                released = await connection.fetchval(
                    "SELECT pg_advisory_unlock(hashtextextended('research-gpu', 0))"
                )
                if released is not True:
                    connection.terminate()
                    raise RuntimeError("research GPU advisory lock was not held")
            except BaseException:
                connection.terminate()
                raise
