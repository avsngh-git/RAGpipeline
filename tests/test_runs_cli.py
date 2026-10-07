"""Offline coverage for research run CLI commands."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from research_platform.config import Settings
from research_platform.runs import cli
from research_platform.runs.contracts import ResearchMode, ResearchRunView, RunStatus


class FakePool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeStore:
    def __init__(self, *, removed: tuple[UUID, ...] = ()) -> None:
        self.removed = removed
        self.prune_older_than = None
        self.requested_run_id = None

    async def prune(self, *, older_than):
        self.prune_older_than = older_than
        return self.removed

    async def get_run_view(self, run_id: UUID) -> ResearchRunView:
        self.requested_run_id = run_id
        return ResearchRunView(
            run_id=run_id,
            status=RunStatus.QUEUED,
            mode=ResearchMode.QUICK,
            question="A synthetic research question",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def list_tool_calls(self, run_id: UUID):
        return ()

    async def list_llm_calls(self, run_id: UUID, *, include_payloads: bool = False):
        return ()

    async def list_draft_claims(self, run_id: UUID):
        return ()

    async def get_synthesis_summary(self, run_id: UUID):
        return None

    async def load_evidence(self, run_id: UUID):
        return {}


class FakeSaver:
    pass


def test_prune_deletes_runs_and_checkpoints(monkeypatch, capsys) -> None:
    run_ids = (uuid4(), uuid4())
    pool = FakePool()
    store = FakeStore(removed=run_ids)
    saver = FakeSaver()
    deleted: list[tuple[FakeSaver, UUID]] = []
    entered: list[FakeSaver] = []
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: Settings(database_url="postgresql://test:test@localhost/research_test"),
    )

    async def create_pool(
        database_url: str, *, min_size: int, max_size: int
    ) -> FakePool:
        assert database_url.endswith("/research_test")
        assert (min_size, max_size) == (1, 2)
        return pool

    @asynccontextmanager
    async def open_checkpointer(database_url: str):
        assert database_url.endswith("/research_test")
        entered.append(saver)
        yield saver

    async def delete_run_checkpoints(active_saver: FakeSaver, run_id: UUID) -> None:
        deleted.append((active_saver, run_id))

    monkeypatch.setattr(cli.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(cli, "RunRepository", lambda _pool: store)
    monkeypatch.setattr(cli, "open_checkpointer", open_checkpointer)
    monkeypatch.setattr(cli, "delete_run_checkpoints", delete_run_checkpoints)

    cli.main(["prune", "--older-than-days", "7"])

    assert store.prune_older_than.days == 7
    assert entered == [saver]
    assert deleted == [(saver, run_id) for run_id in run_ids]
    assert capsys.readouterr().out == "2\n"
    assert pool.closed


def test_show_prints_view(monkeypatch, capsys) -> None:
    pool = FakePool()
    store = FakeStore()
    run_id = uuid4()
    used_urls: list[str] = []
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: Settings(database_url="postgresql://test:test@localhost/research_test"),
    )

    async def create_pool(
        database_url: str, *, min_size: int, max_size: int
    ) -> FakePool:
        used_urls.append(database_url)
        return pool

    monkeypatch.setattr(cli.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(cli, "RunRepository", lambda _pool: store)

    cli.main(["show", str(run_id)])

    assert store.requested_run_id == run_id
    assert used_urls == ["postgresql://test:test@localhost/research_test"]
    assert '"status": "queued"' in capsys.readouterr().out
    assert pool.closed


def test_explain_prints_json(monkeypatch, capsys) -> None:
    pool = FakePool()
    store = FakeStore()
    run_id = uuid4()
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: Settings(database_url="postgresql://test:test@localhost/research_test"),
    )

    async def create_pool(
        database_url: str, *, min_size: int, max_size: int
    ) -> FakePool:
        assert database_url.endswith("/research_test")
        return pool

    monkeypatch.setattr(cli.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(cli, "RunRepository", lambda _pool: store)

    cli.main(["explain", str(run_id), "--json"])

    output = capsys.readouterr().out
    assert '"run_id"' in output
    assert '"stage": "in_progress"' in output
    assert pool.closed


def test_prune_rejects_zero_days(monkeypatch) -> None:
    async def create_pool(*_args, **_kwargs):
        raise AssertionError("invalid arguments must be rejected before connecting")

    monkeypatch.setattr(cli.asyncpg, "create_pool", create_pool)

    with pytest.raises(SystemExit) as error:
        cli.main(["prune", "--older-than-days", "0"])

    assert error.value.code == 2
