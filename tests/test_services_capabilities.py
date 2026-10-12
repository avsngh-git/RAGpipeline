"""Tests for shared retrieval capabilities and transport-independent errors."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from research_platform.api import Phase2APIServices
from research_platform.config import Settings
from research_platform.search.contracts import (
    EvidenceHit,
    PaperHit,
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
from research_platform.search.paper_reads import PaperReadStatus
from research_platform.search.paper_related import RelatedPapersPage
from research_platform.services.capabilities import ResearchCapabilities
from research_platform.services.errors import AppError
from research_platform.tools.fakes import (
    FakeCorpus,
    FakePaper,
    FakePassage,
    FakeServices,
    fake_services,
)

SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000099")
PROFILE_ID = "sha256:" + "a" * 64
PAPER_A = "W100"
PAPER_B = "W200"
PAPER_C = "W300"


def _corpus(*, failing_queries: frozenset[str] = frozenset()) -> FakeCorpus:
    return FakeCorpus(
        snapshot_id=SNAPSHOT_ID,
        papers=(
            FakePaper(PAPER_A, "Synthetic paper A", 2021),
            FakePaper(PAPER_B, "Synthetic paper B", 2023),
            FakePaper(PAPER_C, "Synthetic paper C", 2024),
        ),
        passages=(
            FakePassage("chunk-a1", PAPER_A, "zq7731 synthetic evidence"),
            FakePassage("chunk-a2", PAPER_A, "zq7731 second marker"),
            FakePassage("chunk-b1", PAPER_B, "zq7731 synthetic evidence"),
            FakePassage("chunk-c1", PAPER_C, "zq7731 synthetic evidence"),
        ),
        citations=(
            (PAPER_A, PAPER_B),
            (PAPER_B, PAPER_C),
            (PAPER_C, PAPER_A),
            (PAPER_C, PAPER_B),
        ),
        failing_queries=failing_queries,
    )


def _settings(*, access: str = "trusted_private_local") -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://test:test@localhost:5432/research_test",
        qdrant_url="http://localhost:26333",
        evidence_access_profile=access,
    )


def _request(operation: SearchOperation, *, query: str = "zq7731") -> SearchRequest:
    return SearchRequest(
        query=query,
        snapshot_id=SNAPSHOT_ID,
        retrieval_profile_id=PROFILE_ID,
        mode=RetrievalMode.RERANKED,
        operation=operation,
    )


def _capabilities(
    services: tuple[FakeServices, FakeServices, FakeServices, FakeServices]
    | Phase2APIServices
    | None = None,
    *,
    settings: Settings | None = None,
) -> ResearchCapabilities:
    phase2 = services
    if isinstance(services, tuple):
        search, papers, citations, related = services
        phase2 = Phase2APIServices(
            search=search, papers=papers, citations=citations, related=related
        )
    return ResearchCapabilities(settings=settings or _settings(), phase2=phase2)


def test_search_papers_returns_the_service_response() -> None:
    services = fake_services(_corpus())
    capabilities = _capabilities(services)
    result = asyncio.run(
        capabilities.search_papers(
            _request(SearchOperation.PAPER_SEARCH), request_id="synthetic-request"
        )
    )

    assert all(isinstance(hit, PaperHit) for hit in result.hits)
    assert {hit.paper_id for hit in result.hits} == {PAPER_A, PAPER_B, PAPER_C}


def test_search_evidence_returns_evidence_hits() -> None:
    services = fake_services(_corpus())
    capabilities = _capabilities(services)
    result = asyncio.run(
        capabilities.search_evidence(
            _request(SearchOperation.EVIDENCE_SEARCH), request_id="synthetic-request"
        )
    )

    assert result.hits
    assert all(isinstance(hit, EvidenceHit) for hit in result.hits)


def test_search_requires_trusted_private_evidence() -> None:
    capabilities = _capabilities(settings=_settings(access="disabled"))

    with pytest.raises(AppError) as error:
        asyncio.run(
            capabilities.search_papers(
                _request(SearchOperation.PAPER_SEARCH), request_id="synthetic-request"
            )
        )

    assert error.value.code == "permission_denied"
    assert error.value.status_code == 403


def test_search_rejects_the_wrong_operation() -> None:
    capabilities = _capabilities(fake_services(_corpus()))

    with pytest.raises(AppError) as error:
        asyncio.run(
            capabilities.search_papers(
                _request(SearchOperation.EVIDENCE_SEARCH),
                request_id="synthetic-request",
            )
        )

    assert error.value.code == "invalid_request"
    assert error.value.status_code == 422


def test_missing_service_is_503() -> None:
    capabilities = ResearchCapabilities(_settings(), None)

    async def exercise() -> None:
        with pytest.raises(AppError) as papers_error:
            await capabilities.search_papers(
                _request(SearchOperation.PAPER_SEARCH), request_id="synthetic-request"
            )
        with pytest.raises(AppError) as evidence_error:
            await capabilities.search_evidence(
                _request(SearchOperation.EVIDENCE_SEARCH),
                request_id="synthetic-request",
            )
        with pytest.raises(AppError) as paper_error:
            await capabilities.read_paper(SNAPSHOT_ID, PAPER_A)
        with pytest.raises(AppError) as citation_error:
            await capabilities.citation_page(
                SNAPSHOT_ID,
                PAPER_A,
                CitationDirection.REFERENCES,
                limit=20,
                cursor=None,
            )
        with pytest.raises(AppError) as related_error:
            await capabilities.related_papers(SNAPSHOT_ID, PAPER_A, limit=10)

        for error in (
            papers_error.value,
            evidence_error.value,
            paper_error.value,
            citation_error.value,
            related_error.value,
        ):
            assert error.code == "service_unavailable"
            assert error.status_code == 503

    asyncio.run(exercise())


def test_dependency_failure_is_mapped() -> None:
    services = fake_services(_corpus(failing_queries=frozenset({"zq7731"})))
    capabilities = _capabilities(services)

    with pytest.raises(AppError) as error:
        asyncio.run(
            capabilities.search_papers(
                _request(SearchOperation.PAPER_SEARCH), request_id="synthetic-request"
            )
        )

    assert error.value.code == "dependency_unavailable"
    assert error.value.status_code == 503


def test_mismatched_response_is_500() -> None:
    fake = fake_services(_corpus())[0]

    class MismatchedSearch:
        async def execute(
            self, request: SearchRequest, *, request_id: str
        ) -> SearchResponse[PaperHit] | SearchResponse[EvidenceHit]:
            response = await fake.execute(request, request_id=request_id)
            return replace(response, snapshot_id=OTHER_SNAPSHOT_ID)

    capabilities = _capabilities(Phase2APIServices(search=MismatchedSearch()))

    with pytest.raises(AppError) as error:
        asyncio.run(
            capabilities.search_papers(
                _request(SearchOperation.PAPER_SEARCH), request_id="synthetic-request"
            )
        )

    assert error.value.code == "invalid_service_response"
    assert error.value.status_code == 500


def test_citation_page_round_trips_its_cursor() -> None:
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
                endpoint_identifier="zq7731",
                edge_source="synthetic-source",
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
                            external_namespace="synthetic",
                            external_identifier="zq7731",
                        ),
                        source="synthetic-source",
                    ),
                ),
                next_cursor=next_cursor,
                coverage_note="Synthetic stored relationships.",
            )

    citations = StubCitations()
    capabilities = _capabilities(Phase2APIServices(citations=citations))

    async def exercise() -> tuple[str | None, CitationGraphCursor | None]:
        _, encoded = await capabilities.citation_page(
            SNAPSHOT_ID,
            PAPER_A,
            CitationDirection.REFERENCES,
            limit=20,
            cursor=None,
        )
        first_cursor = citations.cursor
        await capabilities.citation_page(
            SNAPSHOT_ID,
            PAPER_A,
            CitationDirection.REFERENCES,
            limit=20,
            cursor=encoded,
        )
        return encoded, first_cursor

    encoded, first_cursor = asyncio.run(exercise())

    assert encoded is not None
    assert first_cursor is None
    assert citations.cursor == CitationGraphCursor(
        snapshot_id=SNAPSHOT_ID,
        paper_id=PAPER_A,
        direction=CitationDirection.REFERENCES,
        endpoint_kind="external",
        endpoint_identifier="zq7731",
        edge_source="synthetic-source",
    )


def test_invalid_cursor_is_422() -> None:
    capabilities = _capabilities(
        Phase2APIServices(citations=fake_services(_corpus())[2])
    )

    with pytest.raises(AppError) as error:
        asyncio.run(
            capabilities.citation_page(
                SNAPSHOT_ID,
                PAPER_A,
                CitationDirection.REFERENCES,
                limit=20,
                cursor="not-base64!",
            )
        )

    assert error.value.code == "invalid_cursor"
    assert error.value.status_code == 422


def test_related_papers_uses_the_related_service() -> None:
    services = fake_services(_corpus())
    capabilities = _capabilities(services)
    result = asyncio.run(capabilities.related_papers(SNAPSHOT_ID, PAPER_A, limit=10))

    assert isinstance(result, RelatedPapersPage)
    assert result.paper_id == PAPER_A
    assert result.papers


def test_from_app_state_reads_settings_and_services() -> None:
    settings = _settings()
    services = Phase2APIServices()
    capabilities = ResearchCapabilities.from_app_state(
        SimpleNamespace(settings=settings, phase2_services=services)
    )

    assert capabilities.settings is settings
    assert capabilities.phase2 is services


def test_moved_names_are_still_importable() -> None:
    import research_platform.api as api
    from research_platform.api.errors import AppError as ApiAppError
    from research_platform.services.capabilities import Phase2APIServices as ServiceSet
    from research_platform.services.errors import AppError as ServiceAppError

    assert api.Phase2APIServices is ServiceSet
    assert ApiAppError is ServiceAppError
