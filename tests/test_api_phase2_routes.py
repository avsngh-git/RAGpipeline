"""Transport tests for the Phase 2 search and paper APIs."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

import httpx
from fastapi import FastAPI

from research_platform.api import Phase2APIServices, create_app
from research_platform.config import Settings
from research_platform.search.contracts import (
    RetrievalMode,
    SearchOperation,
    SearchRequest,
    SearchResponse,
)
from research_platform.search.paper_graph import (
    CitationDirection,
    CitationEndpointStatus,
    CitationGraphCursor,
    CitationGraphEdge,
    CitationGraphEndpoint,
    CitationGraphPage,
)
from research_platform.search.paper_reads import (
    MetadataAvailability,
    PaperReadStatus,
    SnapshotNotFound,
    SnapshotPaperRead,
)
from research_platform.services.readiness import ReadinessReport

SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
PROFILE_ID = "sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870"


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


class StubSearch:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.requests: list[SearchRequest] = []

    async def execute(
        self, request: SearchRequest, *, request_id: str
    ) -> SearchResponse[object]:
        if self.fail is not None:
            raise self.fail
        self.requests.append(request)
        return SearchResponse(
            request_id=request_id,
            snapshot_id=request.snapshot_id,
            retrieval_profile_id=request.retrieval_profile_id,
            effective_configuration_id=PROFILE_ID,
            requested_mode=request.mode,
            effective_mode=(
                RetrievalMode.HYBRID
                if request.mode is RetrievalMode.RERANKED
                else request.mode
            ),
            hits=(),
            eligible_count=0,
            warnings=(
                ("reranker failed; unchanged hybrid order was returned",)
                if request.mode is RetrievalMode.RERANKED
                else ()
            ),
        )


class StubPapers:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.calls: list[tuple[UUID, str]] = []

    async def read_paper(self, snapshot_id: UUID, paper_id: str) -> SnapshotPaperRead:
        if self.fail is not None:
            raise self.fail
        self.calls.append((snapshot_id, paper_id))
        return SnapshotPaperRead(
            paper_id=paper_id,
            snapshot_id=snapshot_id,
            status=PaperReadStatus.IN_SNAPSHOT,
            title="Synthetic paper title",
            publication_year=2024,
            metadata_availability=MetadataAvailability(
                title=True, abstract=True, publication_year=True
            ),
            document_id=UUID("cebec6e2-0f38-4dcb-8f89-2042a7d631e7"),
            document_version="synthetic-v1",
            document_version_kind="published",
        )


class StubCitations:
    def __init__(self) -> None:
        self.cursor: CitationGraphCursor | None = None

    async def read_one_hop(
        self,
        snapshot_id: UUID,
        paper_id: str,
        direction: CitationDirection,
        *,
        limit: int = 20,
        cursor: CitationGraphCursor | None = None,
    ) -> CitationGraphPage:
        self.cursor = cursor
        next_cursor = CitationGraphCursor(
            snapshot_id=snapshot_id,
            paper_id=paper_id,
            direction=direction,
            endpoint_kind="external",
            endpoint_identifier="10.5555/example.2",
            edge_source="synthetic-reference-list",
        )
        return CitationGraphPage(
            snapshot_id=snapshot_id,
            paper_id=paper_id,
            direction=direction,
            source_status=PaperReadStatus.IN_SNAPSHOT,
            limit=limit,
            edges=(
                CitationGraphEdge(
                    endpoint=CitationGraphEndpoint(
                        status=CitationEndpointStatus.UNRESOLVED,
                        paper_id=None,
                        title=None,
                        publication_year=None,
                        external_namespace="doi",
                        external_identifier="10.5555/example.1",
                    ),
                    source="synthetic-reference-list",
                ),
            ),
            next_cursor=next_cursor,
            coverage_note="Stored local relationships only.",
        )


def _settings(*, access: str = "trusted_private_local") -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://test:test@localhost:5432/research_test",
        qdrant_url="http://localhost:26333",
        evidence_access_profile=access,
    )


def _app(
    *,
    access: str = "trusted_private_local",
    search: StubSearch | None = None,
    papers: StubPapers | None = None,
    citations: StubCitations | None = None,
) -> FastAPI:
    return create_app(
        settings=_settings(access=access),
        dependency_checker=StubReadinessChecker(),
        api_services=Phase2APIServices(
            search=search,
            papers=papers,
            citations=citations,
        ),
    )


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=body)


def _search_body(*, mode: str = "reranked") -> dict[str, object]:
    return {
        "query": "synthetic test query",
        "snapshot_id": str(SNAPSHOT_ID),
        "retrieval_profile_id": PROFILE_ID,
        "mode": mode,
        "limit": 10,
    }


def test_search_routes_delegate_and_report_fallback_mode() -> None:
    search = StubSearch()
    app = _app(search=search)

    paper = asyncio.run(_request(app, "POST", "/v1/search", body=_search_body()))
    evidence = asyncio.run(
        _request(app, "POST", "/v1/evidence/search", body=_search_body())
    )

    assert paper.status_code == 200
    assert evidence.status_code == 200
    assert paper.json()["result_status"] == "no_eligible_records"
    assert paper.json()["hits"] == []
    assert evidence.json()["requested_mode"] == "reranked"
    assert evidence.json()["effective_mode"] == "hybrid"
    assert evidence.json()["warnings"] == [
        "reranker failed; unchanged hybrid order was returned"
    ]
    assert len(search.requests) == 2
    assert all(
        request.operation is SearchOperation.PAPER_SEARCH
        for request in [search.requests[0]]
    )
    assert search.requests[1].operation is SearchOperation.EVIDENCE_SEARCH


def test_search_is_denied_when_server_evidence_access_is_disabled() -> None:
    response = asyncio.run(
        _request(
            _app(access="disabled", search=StubSearch()),
            "POST",
            "/v1/search",
            body=_search_body(),
        )
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_search_validation_uses_stable_error_envelope() -> None:
    body = _search_body()
    body["unknown_field"] = "rejected"
    response = asyncio.run(
        _request(_app(search=StubSearch()), "POST", "/v1/search", body=body)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "unknown_field" not in response.text


def test_search_without_backend_returns_dependency_error() -> None:
    response = asyncio.run(_request(_app(), "POST", "/v1/search", body=_search_body()))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_paper_metadata_read_has_no_passage_field() -> None:
    papers = StubPapers()
    response = asyncio.run(
        _request(
            _app(papers=papers),
            "GET",
            f"/v1/papers/W123?snapshot_id={SNAPSHOT_ID}",
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_snapshot"
    assert body["title"] == "Synthetic paper title"
    assert body["document_version"] == "synthetic-v1"
    assert "text" not in body
    assert "abstract" not in body
    assert papers.calls == [(SNAPSHOT_ID, "W123")]


def test_unknown_snapshot_maps_to_safe_not_found_error() -> None:
    response = asyncio.run(
        _request(
            _app(papers=StubPapers(fail=SnapshotNotFound("internal detail"))),
            "GET",
            f"/v1/papers/W123?snapshot_id={SNAPSHOT_ID}",
        )
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "snapshot_not_found"
    assert "internal detail" not in response.text


def test_citation_route_returns_unresolved_edges_and_roundtrips_cursor() -> None:
    citations = StubCitations()
    app = _app(citations=citations)
    path = f"/v1/papers/W123/references?snapshot_id={SNAPSHOT_ID}&limit=2"

    first = asyncio.run(_request(app, "GET", path))
    cursor = first.json()["next_cursor"]
    second = asyncio.run(_request(app, "GET", f"{path}&cursor={cursor}"))

    assert first.status_code == 200
    assert first.json()["edges"][0]["endpoint"]["status"] == "unresolved"
    assert (
        first.json()["edges"][0]["endpoint"]["external_identifier"]
        == "10.5555/example.1"
    )
    assert first.json()["has_more"] is True
    assert second.status_code == 200
    assert citations.cursor is not None
    assert citations.cursor.endpoint_identifier == "10.5555/example.2"


def test_invalid_or_cross_route_cursor_is_rejected() -> None:
    response = asyncio.run(
        _request(
            _app(citations=StubCitations()),
            "GET",
            f"/v1/papers/W123/citations?snapshot_id={SNAPSHOT_ID}&cursor=not-a-cursor",
        )
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_all_phase2_routes_and_synthetic_examples_are_in_openapi() -> None:
    app = _app(search=StubSearch(), papers=StubPapers(), citations=StubCitations())
    schema = json.dumps(app.openapi(), sort_keys=True)

    for path in (
        "/v1/search",
        "/v1/evidence/search",
        "/v1/papers/{paper_id}",
        "/v1/papers/{paper_id}/references",
        "/v1/papers/{paper_id}/citations",
    ):
        assert path in schema
    assert "synthetic test: a prose passage" in schema
    assert "synthetic test: values in a benchmark table" in schema
    assert "reranking failed; unchanged hybrid order was returned" in schema
    assert "10.5555/example.1" in schema
