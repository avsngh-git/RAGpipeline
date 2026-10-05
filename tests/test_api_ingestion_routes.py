"""Transport coverage for API-started collection ingestion (P35-28)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.config import Settings
from research_platform.ingestion.membership_policy import (
    MembershipDecision,
    PolicyResult,
)
from research_platform.services.readiness import ReadinessReport
from research_platform.worker.queue import IngestionRequest

READY = UUID("11111111-1111-4111-8111-111111111111")
UNPUBLISHED = UUID("22222222-2222-4222-8222-222222222222")
OTHER = UUID("33333333-3333-4333-8333-333333333333")


class _Readiness:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


class _Service:
    def __init__(self) -> None:
        self.requests: dict[UUID, IngestionRequest] = {}
        self.submitted: list[tuple[UUID, tuple[str, ...]]] = []

    async def collection_state(self, collection_id: UUID):
        if collection_id == READY or collection_id == OTHER:
            return "ready"
        return "unpublished" if collection_id == UNPUBLISHED else "missing"

    async def submit(self, collection_id: UUID, paper_ids: Sequence[str]):
        self.submitted.append((collection_id, tuple(paper_ids)))
        decisions = tuple(
            MembershipDecision(
                paper_id,
                "accepted" if paper_id.startswith("W1") else "refused",
                "accepted" if paper_id.startswith("W1") else "already_indexed",
            )
            for paper_id in paper_ids
        )
        accepted = tuple(d.paper_id for d in decisions if d.decision == "accepted")
        if not accepted:
            return PolicyResult(None, decisions)
        request_id = uuid4()
        self.requests[request_id] = IngestionRequest(
            request_id, collection_id, None, "api", accepted, "pending", 0, {}
        )
        return PolicyResult(request_id, decisions)

    async def get_request(self, request_id: UUID):
        return self.requests.get(request_id)


def _app(service: _Service) -> FastAPI:
    return create_app(
        settings=Settings(
            environment="test",
            database_url="postgresql://test:test@localhost:5432/research_test",
            qdrant_url="http://localhost:26333",
        ),
        dependency_checker=_Readiness(),
        ingestion_service=service,
    )


async def _call(
    app: FastAPI, method: str, path: str, body: object = None
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=body)


def test_post_enqueues_and_returns_decisions() -> None:
    service = _Service()
    response = asyncio.run(
        _call(
            _app(service),
            "POST",
            f"/v1/collections/{READY}/ingest",
            {"paper_ids": ["W101", "W900"]},
        )
    )

    assert response.status_code == 202
    body = response.json()
    assert body["request_id"] is not None and body["status"] == "pending"
    assert [(d["paper_id"], d["decision"], d["reason"]) for d in body["decisions"]] == [
        ("W101", "accepted", "accepted"),
        ("W900", "refused", "already_indexed"),
    ]
    assert service.submitted == [(READY, ("W101", "W900"))]


def test_post_all_refused_returns_null_request() -> None:
    response = asyncio.run(
        _call(
            _app(_Service()),
            "POST",
            f"/v1/collections/{READY}/ingest",
            {"paper_ids": ["W900"]},
        )
    )

    assert response.status_code == 202
    assert response.json()["request_id"] is None
    assert response.json()["status"] is None


def test_unknown_collection_404() -> None:
    response = asyncio.run(
        _call(
            _app(_Service()),
            "POST",
            f"/v1/collections/{uuid4()}/ingest",
            {"paper_ids": ["W101"]},
        )
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "collection_not_found"


def test_unpublished_collection_409() -> None:
    response = asyncio.run(
        _call(
            _app(_Service()),
            "POST",
            f"/v1/collections/{UNPUBLISHED}/ingest",
            {"paper_ids": ["W101"]},
        )
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "collection_not_ready"


def test_body_validation() -> None:
    app = _app(_Service())
    for body in (
        {"paper_ids": []},
        {"paper_ids": [f"W{i}" for i in range(21)]},
        {"paper_ids": ["W1"], "run_id": str(uuid4())},
        {},
    ):
        response = asyncio.run(
            _call(app, "POST", f"/v1/collections/{READY}/ingest", body)
        )
        assert response.status_code == 422
        assert "Traceback" not in response.text


def test_get_returns_status_and_outcomes() -> None:
    service = _Service()
    app = _app(service)
    created = asyncio.run(
        _call(app, "POST", f"/v1/collections/{READY}/ingest", {"paper_ids": ["W101"]})
    ).json()
    request_id = UUID(created["request_id"])
    stored = service.requests[request_id]
    service.requests[request_id] = IngestionRequest(
        stored.id,
        stored.collection_id,
        None,
        "api",
        stored.paper_ids,
        "succeeded",
        1,
        {
            "generation": 3,
            "outcomes": [
                {"paper_id": "W101", "status": "ingested", "reason": "ingested"}
            ],
        },
    )

    response = asyncio.run(
        _call(app, "GET", f"/v1/collections/{READY}/ingest/{request_id}")
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["generation"]) == ("succeeded", 3)
    assert body["outcomes"] == [
        {"paper_id": "W101", "status": "ingested", "reason": "ingested"}
    ]


def test_get_other_collection_404() -> None:
    service = _Service()
    app = _app(service)
    created = asyncio.run(
        _call(app, "POST", f"/v1/collections/{READY}/ingest", {"paper_ids": ["W101"]})
    ).json()

    response = asyncio.run(
        _call(app, "GET", f"/v1/collections/{OTHER}/ingest/{created['request_id']}")
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ingestion_request_not_found"


def test_openapi_lists_both_routes() -> None:
    paths = _app(_Service()).openapi()["paths"]
    assert "post" in paths["/v1/collections/{collection_id}/ingest"]
    assert "get" in paths["/v1/collections/{collection_id}/ingest/{request_id}"]
