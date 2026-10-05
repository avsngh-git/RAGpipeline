"""Live PostgreSQL and Qdrant coverage for the ingestion membership policy (P35-26)."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import httpx
import pytest

from research_platform.config import DiscoverySettings
from research_platform.ingestion import membership_policy
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationPoint,
    GenerationQdrantCollection,
    paper_point_id,
)
from research_platform.ingestion.generation_registry import GenerationRegistry
from research_platform.ingestion.membership_policy import (
    POLICY_REVISION,
    MembershipPolicy,
)
from research_platform.persistence.migrations import apply_migrations

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")
TEST_QDRANT_URL = os.environ.get("RESEARCH_PLATFORM_TEST_QDRANT_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL or not TEST_QDRANT_URL,
        reason="requires the dedicated disposable PostgreSQL and Qdrant services",
    ),
]


async def _papers(pool: asyncpg.Pool, http: httpx.AsyncClient, suffix: str):
    """Catalog papers: new, indexed, old and German; returns their IDs."""
    ids = {
        name: f"W{uuid4().int % 10**12}"
        for name in ("new", "indexed", "old", "german", "other")
    }
    rows = {
        "new": (2024, "en", None),
        "indexed": (2024, "en", 1),
        "old": (2015, "en", None),
        "german": (2024, "de", None),
        "other": (2023, "en", None),
    }
    configuration = GenerationIndexConfiguration(
        passages_collection=f"phase35-policy-passages-{suffix}",
        papers_collection=f"phase35-policy-papers-{suffix}",
        embedding_model="integration-fixture",
        embedding_revision="v1",
        preprocessing_revision="raw-text-v1",
        vector_size=2,
        distance="Cosine",
        batch_size=8,
        maximum_input_tokens=32,
    )
    papers = GenerationQdrantCollection(configuration, "papers", http)
    await papers.ensure_collection()
    points = []
    async with pool.acquire() as connection:
        for name, (year, language, indexed) in rows.items():
            await connection.execute(
                "INSERT INTO papers (id, title, publication_year, metadata) "
                "VALUES ($1, $2, $3, $4::jsonb)",
                ids[name],
                f"Paper {name}",
                year,
                json.dumps({"language": language}),
            )
            payload: dict[str, object] = {
                "paper_id": ids[name],
                "publication_year": year,
                "catalog_status": "metadata_only",
            }
            if indexed is not None:
                payload["indexed_generation"] = indexed
            points.append(
                GenerationPoint(
                    paper_point_id(ids[name], configuration.configuration_id),
                    (1.0, 0.0),
                    None,
                    payload,
                )
            )
    await papers.upsert(points)
    return ids, papers


def _with_policy(
    operation: Callable[
        [asyncpg.Pool, MembershipPolicy, dict[str, str]], Awaitable[None]
    ],
) -> None:
    assert TEST_DATABASE_URL is not None and TEST_QDRANT_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=4)
        http = httpx.AsyncClient(base_url=TEST_QDRANT_URL, timeout=30)
        suffix = uuid4().hex[:12]
        papers = None
        try:
            ids, papers = await _papers(pool, http, suffix)
            collection_id = await GenerationRegistry(pool).ensure_collection(
                f"policy-{suffix}"
            )
            policy = MembershipPolicy(
                pool, papers, DiscoverySettings(), collection_id=collection_id
            )
            await operation(pool, policy, ids)
        finally:
            if papers is not None:
                await http.delete(f"/collections/{papers.name}")
            await http.aclose()
            await pool.close()

    asyncio.run(exercise())


async def _rows(pool: asyncpg.Pool, paper_ids: list[str]):
    async with pool.acquire() as connection:
        decisions = await connection.fetch(
            "SELECT paper_id, decision, reason, request_id, policy_revision "
            "FROM ingestion_decisions WHERE paper_id = ANY($1::text[]) ORDER BY id",
            paper_ids,
        )
        requests = await connection.fetch(
            "SELECT id, paper_ids, requested_by, status FROM ingestion_requests "
            "WHERE paper_ids && $1::text[]",
            paper_ids,
        )
    return decisions, requests


def test_accepted_papers_enqueued_with_decisions() -> None:
    async def operation(pool, policy, ids) -> None:
        proposed = [ids[name] for name in ("new", "indexed", "old", "german", "other")]
        proposed.append("W999999999999999")
        result = await policy.submit(
            run_id=None, requested_by="terminal", paper_ids=proposed, max_papers=5
        )
        assert [d.reason for d in result.decisions] == [
            "accepted",
            "already_indexed",
            "out_of_scope_year",
            "out_of_scope_language",
            "accepted",
            "unknown_paper",
        ]
        decisions, requests = await _rows(pool, proposed)
        assert len(decisions) == 6
        assert {row["policy_revision"] for row in decisions} == {POLICY_REVISION}
        assert len(requests) == 1 and requests[0]["id"] == result.request_id
        assert list(requests[0]["paper_ids"]) == [ids["new"], ids["other"]]
        accepted_rows = [row for row in decisions if row["decision"] == "accepted"]
        assert {row["request_id"] for row in accepted_rows} == {result.request_id}
        assert all(
            row["request_id"] is None
            for row in decisions
            if row["decision"] == "refused"
        )

    _with_policy(operation)


def test_all_refused_creates_no_request() -> None:
    async def operation(pool, policy, ids) -> None:
        proposed = [ids["indexed"], ids["old"]]
        result = await policy.submit(
            run_id=None, requested_by="api", paper_ids=proposed, max_papers=5
        )
        assert result.request_id is None
        decisions, requests = await _rows(pool, proposed)
        assert len(decisions) == 2 and requests == []

    _with_policy(operation)


def test_duplicate_pending_request_refused() -> None:
    async def operation(pool, policy, ids) -> None:
        first = await policy.submit(
            run_id=None, requested_by="api", paper_ids=[ids["new"]], max_papers=5
        )
        second = await policy.submit(
            run_id=None, requested_by="api", paper_ids=[ids["new"]], max_papers=5
        )
        assert first.request_id is not None and second.request_id is None
        assert second.decisions[0].reason == "duplicate_request"

    _with_policy(operation)


def test_rollback_leaves_no_decision_or_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = membership_policy.IngestionQueue.enqueue

    async def enqueue_then_fail(connection, **kwargs):
        await original(connection, **kwargs)
        raise RuntimeError("simulated failure after enqueue")

    monkeypatch.setattr(
        membership_policy.IngestionQueue, "enqueue", staticmethod(enqueue_then_fail)
    )

    async def operation(pool, policy, ids) -> None:
        with pytest.raises(RuntimeError, match="simulated"):
            await policy.submit(
                run_id=None, requested_by="api", paper_ids=[ids["new"]], max_papers=5
            )
        decisions, requests = await _rows(pool, [ids["new"]])
        assert decisions == [] and requests == []

    _with_policy(operation)
