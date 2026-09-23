"""Timeout behavior for live dependency checks."""

import asyncio
from time import monotonic

import pytest

from research_platform.config import Settings
from research_platform.services.readiness import LiveDependencyChecker


class StalledQueryConnection:
    def __init__(self) -> None:
        self.terminated = False

    async def fetchval(self, _query: str) -> int:
        await asyncio.Event().wait()

    async def close(self) -> None:
        raise AssertionError("a timed-out connection should be terminated")

    def terminate(self) -> None:
        self.terminated = True


class StalledCloseConnection:
    def __init__(self) -> None:
        self.terminated = False

    async def fetchval(self, _query: str) -> int:
        return 1

    async def close(self) -> None:
        await asyncio.Event().wait()

    def terminate(self) -> None:
        self.terminated = True


def _use_healthy_qdrant(monkeypatch: pytest.MonkeyPatch) -> None:
    async def check_qdrant(_checker: LiveDependencyChecker) -> bool:
        return True

    monkeypatch.setattr(LiveDependencyChecker, "_check_qdrant", check_qdrant)


def test_postgres_query_timeout_terminates_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = StalledQueryConnection()

    async def connect(_database_url: str, *, timeout: float) -> StalledQueryConnection:
        assert timeout == 0.03
        return connection

    monkeypatch.setattr("research_platform.services.readiness.asyncpg.connect", connect)
    _use_healthy_qdrant(monkeypatch)
    checker = LiveDependencyChecker(Settings(dependency_timeout_seconds=0.03))

    started_at = monotonic()
    report = asyncio.run(checker.check())
    elapsed = monotonic() - started_at

    assert report.dependencies == {"postgres": False, "qdrant": True}
    assert connection.terminated
    assert elapsed < 0.5


def test_postgres_cleanup_timeout_terminates_and_fails_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = StalledCloseConnection()

    async def connect(_database_url: str, *, timeout: float) -> StalledCloseConnection:
        assert timeout == 0.03
        return connection

    monkeypatch.setattr("research_platform.services.readiness.asyncpg.connect", connect)
