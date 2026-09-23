"""Dependency readiness checks for PostgreSQL and Qdrant."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol, cast

import asyncpg  # type: ignore[import-untyped]
import httpx

from research_platform.config import Settings

logger = logging.getLogger("research_platform.readiness")


@dataclass(frozen=True)
class ReadinessReport:
    """Safe dependency status without connection details or secrets."""

    dependencies: dict[str, bool]

    @property
    def ready(self) -> bool:
        return all(self.dependencies.values())


class ReadinessChecker(Protocol):
    """Boundary used by the API and replaceable in tests."""

    async def check(self) -> ReadinessReport: ...


class LiveDependencyChecker:
    """Check live PostgreSQL and Qdrant services with bounded timeouts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def check(self) -> ReadinessReport:
        checks = await asyncio.gather(
            self._check_postgres(),
            self._check_qdrant(),
            return_exceptions=True,
        )
        names = ("postgres", "qdrant")
        statuses: dict[str, bool] = {}
        for name, result in zip(names, checks, strict=True):
            if isinstance(result, BaseException):
                logger.warning("dependency_unavailable", extra={"dependency": name})
                statuses[name] = False
            else:
                statuses[name] = result
        return ReadinessReport(dependencies=statuses)

    async def _check_postgres(self) -> bool:
        timeout_seconds = self._settings.dependency_timeout_seconds
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        connection: asyncpg.Connection | None = None
        try:
            async with asyncio.timeout_at(deadline):
                connection = await asyncpg.connect(
                    self._settings.database_url,
                    timeout=timeout_seconds,
                )
                result = cast(int, await connection.fetchval("SELECT 1"))
            return result == 1
        finally:
            if connection is not None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    connection.terminate()
                else:
                    try:
                        await asyncio.wait_for(connection.close(), timeout=remaining)
                    except TimeoutError:
                        connection.terminate()
                        raise
                    except asyncio.CancelledError:
                        connection.terminate()
                        raise

    async def _check_qdrant(self) -> bool:
        health_url = f"{self._settings.qdrant_url.rstrip('/')}/healthz"
        async with httpx.AsyncClient(
            timeout=self._settings.dependency_timeout_seconds
        ) as client:
            response = await client.get(health_url)
            response.raise_for_status()
            return True
