"""Focused tests for budgeted OpenAlex discovery (P35-19)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest

from research_platform.config import DiscoverySettings
from research_platform.discovery.online import (
    DiscoveryBudgetExceeded,
    OnlineDiscovery,
    SpendLedger,
)
from research_platform.ingestion.catalog import CatalogUpsert
from research_platform.ingestion.config import (
    DiscoveryConfig,
    DiscoveryLimits,
    YearRange,
)
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationMatch,
    GenerationPoint,
    GenerationQdrantCollection,
    paper_point_id,
)
from research_platform.ingestion.indexing import IndexConfiguration
from research_platform.ingestion.openalex import (
    OpenAlexClient,
    OpenAlexPage,
    OpenAlexWork,
)

CONFIGURATION = GenerationIndexConfiguration(
    passages_collection="test-passages",
    papers_collection="test-papers",
    embedding_model="test-model",
    embedding_revision="test-revision",
    preprocessing_revision="test-preprocessing",
    vector_size=2,
    distance="Cosine",
    batch_size=2,
    maximum_input_tokens=512,
)


def _work(openalex_id: str, *, title: str | None = None) -> OpenAlexWork:
    return OpenAlexWork.from_payload(
        {
            "id": f"https://openalex.org/{openalex_id}",
            "title": title or f"Title {openalex_id}",
            "publication_year": 2024,
            "language": "en",
            "type": "article",
            "doi": None,
            "cited_by_count": 3,
            "relevance_score": 1.0,
            "abstract_inverted_index": {"Abstract": [0], "text": [1]},
        }
    )


class _FakeOpenAlex:
    def __init__(self, pages: Sequence[OpenAlexPage], *, page_size: int = 25) -> None:
        self.results_per_request = page_size
        self.pages = list(pages)
        self.requests: list[tuple[str, str, str | None]] = []
        self._reserve_request: Any = None

    @contextmanager
    def request_reservation_scope(self, reserve_request: Any):
        previous = self._reserve_request
        self._reserve_request = reserve_request
        try:
            yield
        finally:
            self._reserve_request = previous

    async def search_page(
        self, query: str, cursor: str, *, extra_filter: str | None = None
    ) -> OpenAlexPage:
        await self._reserve_request()
        self.requests.append((query, cursor, extra_filter))
        return self.pages[len(self.requests) - 1]


class _FakeLedger:
    def __init__(self, *, deny: str | None = None) -> None:
        self.deny = deny
        self.reservations: list[tuple[UUID | None, str, Decimal]] = []
        self.spent = Decimal("0")

    async def reserve(
        self,
        *,
        run_id: UUID | None,
        kind: str,
        cost_usd: Decimal,
        run_limit: int | None,
        daily_cap_usd: Decimal,
    ) -> None:
        del run_limit
        if self.deny is not None:
            raise DiscoveryBudgetExceeded(cast(Any, self.deny))
        if self.spent + cost_usd > daily_cap_usd:
            raise DiscoveryBudgetExceeded("daily_spend_cap")
        self.reservations.append((run_id, kind, cost_usd))
        self.spent += cost_usd


class _FakeCatalog:
    def __init__(self) -> None:
        self.works: list[OpenAlexWork] = []

    async def upsert_openalex_work(
        self, work: OpenAlexWork, metadata: Mapping[str, object]
    ) -> CatalogUpsert:
        del metadata
        self.works.append(work)
        return CatalogUpsert(f"paper-{work.openalex_id}", True, 1)


class _FakePapers:
    def __init__(self) -> None:
        self.payloads: dict[UUID, dict[str, object]] = {}
        self.upserted: list[GenerationPoint] = []
        self.scores: dict[str, float] = {}
        self.query_filter: Mapping[str, object] | None = None

    async def retrieve(
        self, point_ids: Sequence[UUID], *, with_dense: bool = False
    ) -> tuple[GenerationMatch, ...]:
        del with_dense
        return tuple(
            GenerationMatch(point_id, 0.0, self.payloads[point_id])
            for point_id in point_ids
            if point_id in self.payloads
        )

    async def upsert(self, points: Sequence[GenerationPoint]) -> int:
        self.upserted.extend(points)
        for point in points:
            self.payloads[point.point_id] = dict(point.payload)
        return len(points)

    async def query_dense(
        self,
        vector: Sequence[float],
        *,
        filter_: Mapping[str, object],
        limit: int,
    ) -> tuple[GenerationMatch, ...]:
        assert tuple(vector) == (0.0, 1.0)
        self.query_filter = filter_
        matches = [
            GenerationMatch(
                point_id,
                self.scores.get(cast(str, payload["paper_id"]), 0.0),
                payload,
            )
            for point_id, payload in self.payloads.items()
        ]
        return tuple(matches[:limit])


class _FakeEmbedder:
    async def embed(
        self, texts: Sequence[str], *, configuration: IndexConfiguration
    ) -> Sequence[Sequence[float]]:
        del configuration
        return [
            (0.0, 1.0) if text == "Research question" else (1.0, 0.0) for text in texts
        ]


def _page(works: Sequence[OpenAlexWork], next_cursor: str | None) -> OpenAlexPage:
    return OpenAlexPage(next_cursor, tuple(works), len(works), 0.001, {})


def _service(
    pages: Sequence[OpenAlexPage],
    *,
    settings: DiscoverySettings | None = None,
    ledger: _FakeLedger | None = None,
    papers: _FakePapers | None = None,
) -> tuple[OnlineDiscovery, _FakeOpenAlex, _FakeCatalog, _FakePapers, _FakeLedger]:
    active_settings = settings or DiscoverySettings()
    openalex = _FakeOpenAlex(pages, page_size=active_settings.results_per_request)
    catalog = _FakeCatalog()
    collection = papers or _FakePapers()
    active_ledger = ledger or _FakeLedger()
    service = OnlineDiscovery(
        openalex=cast(OpenAlexClient, openalex),
        catalog=cast(Any, catalog),
        papers=cast(GenerationQdrantCollection, collection),
        embedder=cast(Any, _FakeEmbedder()),
        configuration=CONFIGURATION,
        ledger=cast(Any, active_ledger),
        settings=active_settings,
    )
    return service, openalex, catalog, collection, active_ledger


def test_scoped_reservation_runs_for_each_retry() -> None:
    work = _work("W123")
    status = [429, 200]
    reservations: list[bool] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        code = status.pop(0)
        return httpx.Response(
            code,
            headers={"Retry-After": "0"} if code == 429 else {},
            json={
                "meta": {"count": 1, "next_cursor": None},
                "results": [dict(work.metadata)],
            },
        )

    async def no_sleep(_delay: float) -> None:
        return None

    class _RecordingLedger(_FakeLedger):
        async def reserve(self, **kwargs: Any) -> None:
            reservations.append(True)
            await super().reserve(**kwargs)

    async def exercise() -> tuple[object, _RecordingLedger]:
        config = DiscoveryConfig(
            queries=("hybrid retrieval",),
            year_range=YearRange(2020, 2026),
            limits=DiscoveryLimits(per_page=25, max_retries=1),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                config,
                "test-secret",
                http,
                sleep=no_sleep,
                clock=lambda: 0.0,
            )
            catalog = _FakeCatalog()
            papers = _FakePapers()
            ledger = _RecordingLedger()
            service = OnlineDiscovery(
                openalex=client,
                catalog=cast(Any, catalog),
                papers=cast(Any, papers),
                embedder=cast(Any, _FakeEmbedder()),
                configuration=CONFIGURATION,
                ledger=cast(Any, ledger),
                settings=DiscoverySettings(),
            )
            result = await service.discover(
                run_id=uuid4(),
                question="Research question",
                query="hybrid retrieval",
            )
            return result, ledger

    result, ledger = asyncio.run(exercise())

    assert len(result) == 1
    assert len(ledger.reservations) == 2
    assert reservations == [True, True]


def test_run_search_limit_refuses() -> None:
    settings = DiscoverySettings(max_search_requests_per_run=1)
    service, openalex, catalog, _papers, _ledger = _service(
        [_page([_work("W123")], "next"), _page([_work("W456")], None)],
        settings=settings,
    )

    async def exercise() -> None:
        with pytest.raises(DiscoveryBudgetExceeded) as raised:
            await service.discover(
                run_id=uuid4(),
                question="Research question",
                query="hybrid retrieval",
                limit=2,
            )
        assert raised.value.reason == "run_search_limit"

    asyncio.run(exercise())

    assert len(openalex.requests) == 1
    assert catalog.works == []


def test_daily_cap_refuses() -> None:
    class _Connection:
        inserted: list[tuple[object, ...]]

        def __init__(self) -> None:
            self.inserted = []

        @asynccontextmanager
        async def transaction(self):
            yield self

        async def fetchval(self, query: str, *args: object) -> object:
            del args
            if "pg_advisory_xact_lock" in query:
                return None
            if "CURRENT_TIMESTAMP" in query:
                return date(2026, 10, 5)
            if "count(*)" in query:
                return 0
            if "sum(cost_usd)" in query:
                return Decimal("0.50")
            raise AssertionError(f"unexpected SQL: {query}")

        async def execute(self, query: str, *args: object) -> str:
            self.inserted.append(args)
            return "INSERT 0 1"

    class _Pool:
        def __init__(self, connection: _Connection) -> None:
            self.connection = connection

        @asynccontextmanager
        async def acquire(self):
            yield self.connection

    connection = _Connection()
    ledger = SpendLedger(cast(Any, _Pool(connection)))

    async def exercise() -> None:
        with pytest.raises(DiscoveryBudgetExceeded) as raised:
            await ledger.reserve(
                run_id=uuid4(),
                kind="search_request",
                cost_usd=Decimal("0.001"),
                run_limit=10,
                daily_cap_usd=Decimal("0.50"),
            )
        assert raised.value.reason == "daily_spend_cap"

    asyncio.run(exercise())

    assert connection.inserted == []


def test_year_floor_and_field_filter_in_request() -> None:
    service, openalex, _catalog, _papers, _ledger = _service(
        [_page([_work("W123")], None)]
    )

    asyncio.run(
        service.discover(
            run_id=uuid4(),
            question="Research question",
            query="hybrid retrieval",
            year_from=2018,
            year_to=2024,
        )
    )

    assert openalex.requests[0][2] == (
        "publication_year:2020-2024,primary_topic.field.id:17"
    )


def test_results_upserted_as_metadata_only() -> None:
    service, _openalex, _catalog, papers, _ledger = _service(
        [_page([_work("W123")], None)]
    )

    results = asyncio.run(
        service.discover(
            run_id=uuid4(),
            question="Research question",
            query="hybrid retrieval",
        )
    )

    assert len(results) == 1
    assert results[0].catalog_status == "metadata_only"
    payload = papers.upserted[0].payload
    assert payload["catalog_status"] == "metadata_only"
    assert "indexed_generation" not in payload


def test_existing_ingested_paper_keeps_status() -> None:
    papers = _FakePapers()
    point_id = paper_point_id("paper-W123", CONFIGURATION.configuration_id)
    papers.payloads[point_id] = {
        "paper_id": "paper-W123",
        "catalog_status": "ingested",
        "indexed_generation": 3,
    }
    service, _openalex, _catalog, papers, _ledger = _service(
        [_page([_work("W123")], None)], papers=papers
    )

    results = asyncio.run(
        service.discover(
            run_id=uuid4(),
            question="Research question",
            query="hybrid retrieval",
        )
    )

    assert results[0].catalog_status == "ingested"
    assert papers.payloads[point_id]["catalog_status"] == "ingested"
    assert papers.payloads[point_id]["indexed_generation"] == 3


def test_ranked_by_question_similarity() -> None:
    papers = _FakePapers()
    papers.scores = {
        "paper-W123": 0.4,
        "paper-W456": 0.8,
        "paper-W789": 0.99,
    }
    service, _openalex, _catalog, papers, _ledger = _service(
        [_page([_work("W123"), _work("W456"), _work("W789")], None)],
        papers=papers,
    )

    results = asyncio.run(
        service.discover(
            run_id=uuid4(),
            question="Research question",
            query="hybrid retrieval",
            limit=2,
        )
    )

    assert [paper.paper_id for paper in results] == ["paper-W789", "paper-W456"]
    assert [paper.similarity for paper in results] == [0.99, 0.8]
    assert papers.query_filter == {
        "must": [
            {
                "key": "paper_id",
                "match": {"any": ["paper-W123", "paper-W456", "paper-W789"]},
            }
        ]
    }


def test_search_reserves_budget_before_request() -> None:
    service, openalex, catalog, _papers, _ledger = _service(
        [_page([_work("W123")], None)],
        ledger=_FakeLedger(deny="daily_spend_cap"),
    )

    async def exercise() -> None:
        with pytest.raises(DiscoveryBudgetExceeded) as raised:
            await service.discover(
                run_id=uuid4(),
                question="Research question",
                query="hybrid retrieval",
            )
        assert raised.value.reason == "daily_spend_cap"

    asyncio.run(exercise())

    assert openalex.requests == []
    assert catalog.works == []


def test_settings_page_size_must_match_openalex_client() -> None:
    openalex = _FakeOpenAlex([_page([], None)], page_size=100)
    with pytest.raises(ValueError, match="page size must match"):
        OnlineDiscovery(
            openalex=cast(OpenAlexClient, openalex),
            catalog=cast(Any, _FakeCatalog()),
            papers=cast(Any, _FakePapers()),
            embedder=cast(Any, _FakeEmbedder()),
            configuration=CONFIGURATION,
            ledger=cast(Any, _FakeLedger()),
            settings=DiscoverySettings(),
        )
