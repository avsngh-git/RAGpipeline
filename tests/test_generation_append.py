"""Unit tests for appending ingested papers as the next generation (P35-25)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from research_platform.ingestion import generation_append
from research_platform.ingestion.generation_append import (
    ONLINE_REVIEWER,
    AppendReport,
    GenerationAppender,
)
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    SparseLexicalSettings,
)
from research_platform.ingestion.online_ingestion import PaperIngestOutcome
from research_platform.ingestion.snapshots import (
    SnapshotIssue,
    SnapshotValidationReport,
)
from research_platform.worker.handlers import OnlineIngestionHandler, handler_status
from research_platform.worker.queue import IngestionRequest

COLLECTION = uuid4()
PARENT = uuid4()
CHILD = uuid4()
REQUEST = uuid4()
CHUNKING = "sha256:" + "c" * 64


def _configuration(average: float = 40.0) -> GenerationIndexConfiguration:
    return GenerationIndexConfiguration(
        passages_collection="passages",
        papers_collection="papers",
        embedding_model="model",
        embedding_revision="revision",
        preprocessing_revision="preprocessing",
        vector_size=2,
        distance="Cosine",
        batch_size=8,
        maximum_input_tokens=32,
        lexical=SparseLexicalSettings(
            "scientific-en", "v1", "vocabulary", 1.5, 0.75, average, 10.0
        ),
    )


def _ingested(paper_id: str) -> PaperIngestOutcome:
    return PaperIngestOutcome(
        paper_id, "ingested", "ingested", uuid4(), uuid4(), CHUNKING
    )


class _Connection:
    def __init__(self, pool: _Pool) -> None:
        self.pool = pool

    async def execute(self, sql: str, *args: object) -> str:
        if "UPDATE index_generations SET details" in sql:
            self.pool.details.append(args[3])
        return "OK"

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        if "FROM snapshot_items" in sql:
            return [{"paper_id": paper} for paper in self.pool.members]
        return []

    async def fetchval(self, sql: str, *args: object) -> object:
        if "FROM documents" in sql:
            return self.pool.papers_by_document[cast(UUID, args[0])]
        return "sha256:" + "a" * 64

    def terminate(self) -> None:
        pass


@dataclass
class _Pool:
    members: list[str] = field(default_factory=lambda: ["W1", "W2"])
    papers_by_document: dict[UUID, str] = field(default_factory=dict)
    details: list[object] = field(default_factory=list)

    @asynccontextmanager
    async def acquire(self):
        yield _Connection(self)


class _Snapshots:
    def __init__(self, pool: _Pool, issues: tuple[SnapshotIssue, ...] = ()) -> None:
        self.pool = pool
        self.issues = issues
        self.added: list[str] = []
        self.removed: list[str] = []
        self.finalized: dict[str, object] | None = None
        self.validated: list[dict[str, object]] = []

    async def create_variant_draft(self, parent: UUID, **_: object) -> UUID:
        assert parent == PARENT
        return CHILD

    async def configuration_for(self, snapshot_id: UUID) -> dict[str, object]:
        return {"index_configuration_id": "sha256:" + "d" * 64}

    async def add_member(self, snapshot_id: UUID, *, paper_id: str, **_: object):
        self.added.append(paper_id)
        self.pool.members.append(paper_id)

    async def set_chunking_configuration(self, *args: object) -> None:
        assert args[3] == CHUNKING

    async def remove_member(self, snapshot_id: UUID, paper_id: str) -> None:
        self.removed.append(paper_id)

    async def validate(self, snapshot_id: UUID, **kwargs: object):
        self.validated.append(kwargs)
        return SnapshotValidationReport(CHILD, "draft", 0, 0, None, self.issues)

    async def finalize(self, snapshot_id: UUID, **kwargs: object) -> None:
        self.finalized = kwargs


class _Registry:
    def __init__(self) -> None:
        self.published_generation = 1
        self.failed: list[tuple[int, str]] = []

    async def published(self, collection_id: UUID, configuration_id: str):
        return SimpleNamespace(generation=self.published_generation, snapshot_id=PARENT)

    async def mark_failed(self, collection_id, configuration_id, generation, *, reason):
        self.failed.append((generation, reason))


class _Averages:
    def __init__(self, average: float) -> None:
        self.average = average

    async def evidence_average_length(self, snapshot_id: UUID) -> float:
        return self.average


def _appender(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pool: _Pool,
    snapshots: _Snapshots,
    registry: _Registry,
    average: float = 40.0,
    build_error: Exception | None = None,
) -> tuple[GenerationAppender, list[str]]:
    calls: list[str] = []

    async def build(**kwargs: Any):
        calls.append("build")
        assert kwargs["snapshot_id"] == CHILD
        if build_error is not None:
            raise build_error
        return SimpleNamespace(generation=2)

    async def record(name: str, **_: Any):
        calls.append(name)
        return SimpleNamespace(passed=True)

    async def publish(registry_: Any, collection_id, configuration_id, generation):
        calls.append(f"publish:{generation}")
        registry_.published_generation = generation

    monkeypatch.setattr(generation_append, "build_generation_passages", build)
    monkeypatch.setattr(
        generation_append, "sync_papers", lambda **kw: record("sync", **kw)
    )
    monkeypatch.setattr(
        generation_append, "verify_generation", lambda **kw: record("verify", **kw)
    )
    monkeypatch.setattr(generation_append, "publish_generation", publish)
    monkeypatch.setattr(generation_append, "code_revision", lambda: "test")
    appender = GenerationAppender(
        pool=cast(Any, pool),
        registry=cast(Any, registry),
        snapshots=cast(Any, snapshots),
        configuration=_configuration(),
        passages=cast(Any, object()),
        papers=cast(Any, object()),
        embedder=cast(Any, object()),
        sparse_encoder=cast(Any, object()),
        averages=_Averages(average),
    )
    return appender, calls


def test_no_ingested_outcome_creates_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _Pool()
    snapshots = _Snapshots(pool)
    appender, calls = _appender(
        monkeypatch, pool=pool, snapshots=snapshots, registry=_Registry()
    )
    outcomes = (PaperIngestOutcome("W9", "metadata_only", "no_permitted_source"),)

    report = asyncio.run(appender.append(COLLECTION, outcomes, request_id=REQUEST))

    assert report == AppendReport(1, None, None, (), outcomes, 0.0)
    assert calls == [] and snapshots.added == []


def test_child_copies_parent_members_and_adds_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _Pool()
    new, existing = _ingested("W3"), _ingested("W1")
    pool.papers_by_document = {new.document_id: "W3", existing.document_id: "W1"}
    snapshots = _Snapshots(pool)
    appender, calls = _appender(
        monkeypatch, pool=pool, snapshots=snapshots, registry=_Registry()
    )

    report = asyncio.run(
        appender.append(COLLECTION, (new, existing), request_id=REQUEST)
    )

    assert snapshots.added == ["W3"]
    assert snapshots.finalized == {
        "reviewer": ONLINE_REVIEWER,
        "minimum_papers": 3,
        "require_snapshot_index": False,
    }
    assert snapshots.validated[0]["require_snapshot_index"] is False
    assert calls == ["build", "sync", "verify", "publish:2"]
    assert (report.generation, report.snapshot_id, report.added_papers) == (
        2,
        CHILD,
        ("W3",),
    )
    assert {outcome.reason for outcome in report.outcomes} == {
        "ingested",
        "already_member",
    }


def test_paper_specific_validation_issue_removes_only_that_paper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _Pool()
    good, flagged = _ingested("W3"), _ingested("W4")
    pool.papers_by_document = {good.document_id: "W3", flagged.document_id: "W4"}
    issue = SnapshotIssue("flagged_table_review_pending", "review", "W4")
    snapshots = _Snapshots(pool, issues=(issue,))
    appender, _calls = _appender(
        monkeypatch, pool=pool, snapshots=snapshots, registry=_Registry()
    )

    report = asyncio.run(
        appender.append(COLLECTION, (good, flagged), request_id=REQUEST)
    )

    assert snapshots.removed == ["W4"] and report.added_papers == ("W3",)
    rejected = next(o for o in report.outcomes if o.paper_id == "W4")
    assert (rejected.status, rejected.reason) == (
        "failed",
        "validation:flagged_table_review_pending",
    )


def test_build_failure_leaves_pointer_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _Pool()
    new = _ingested("W3")
    pool.papers_by_document = {new.document_id: "W3"}
    registry = _Registry()
    appender, calls = _appender(
        monkeypatch,
        pool=pool,
        snapshots=_Snapshots(pool),
        registry=registry,
        build_error=RuntimeError("qdrant unavailable"),
    )

    with pytest.raises(RuntimeError, match="qdrant unavailable"):
        asyncio.run(appender.append(COLLECTION, (new,), request_id=REQUEST))

    assert calls == ["build"]
    assert registry.published_generation == 1


def test_drift_flag_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _Pool()
    new = _ingested("W3")
    pool.papers_by_document = {new.document_id: "W3"}
    appender, calls = _appender(
        monkeypatch,
        pool=pool,
        snapshots=_Snapshots(pool),
        registry=_Registry(),
        average=46.0,
    )

    report = asyncio.run(appender.append(COLLECTION, (new,), request_id=REQUEST))

    assert report.average_length_drift == pytest.approx(0.15)
    assert len(pool.details) == 1 and "new_configuration_recommended" in str(
        pool.details[0]
    )
    assert calls[-1] == "publish:2"


def test_handler_status_from_outcomes() -> None:
    ingested, metadata = _ingested("W1"), PaperIngestOutcome("W2", "metadata_only", "x")
    assert handler_status(2, (ingested, _ingested("W2"))) == "succeeded"
    assert handler_status(2, (ingested, metadata)) == "partially_succeeded"
    assert handler_status(1, (metadata,)) == "failed"

    class _Ingester:
        async def ingest_paper(self, paper_id: str, *, run_id: UUID | None):
            return _ingested(paper_id) if paper_id == "W1" else metadata

    class _Appender:
        async def append(self, collection_id, outcomes, *, request_id):
            return AppendReport(1, 2, CHILD, ("W1",), tuple(outcomes), 0.0)

    @asynccontextmanager
    async def appender():
        yield _Appender()

    @asynccontextmanager
    async def no_lock(_pool):
        yield

    released: list[bool] = []

    async def release() -> None:
        released.append(True)

    async def chunking_for(collection_id: UUID):
        return {"schema_version": 1}

    handler = OnlineIngestionHandler(
        pool=cast(Any, object()),
        chunking_for=chunking_for,
        ingester=lambda chunking: _Ingester(),
        appender=appender,
        release_gpu=release,
        lock=no_lock,
    )
    request = IngestionRequest(
        REQUEST, COLLECTION, None, "terminal", ("W1", "W2"), "claimed", 1, {}
    )
    status, result = asyncio.run(handler.handle(request))
    assert status == "partially_succeeded" and released == [True]
    assert result["generation"] == 2 and result["added_papers"] == ["W1"]
