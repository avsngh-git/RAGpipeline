"""Offline tests for typed research tools and their deterministic service fakes."""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from research_platform.agents.actions import (
    DiscoverPapersAction,
    FindRelatedPapersAction,
    GetCitationsAction,
    GetPaperAction,
    GetReferencesAction,
    SearchEvidenceAction,
    SearchPapersAction,
)
from research_platform.discovery.online import (
    DiscoveredPaper,
    DiscoveryBudgetExceeded,
)
from research_platform.runs.contracts import ResearchFilters, ResearchMode, RunBudgets
from research_platform.search.access import EvidenceAccessDenied
from research_platform.search.application_errors import (
    IncompatibleRetrievalProfile,
    RetrievalExecutionFailure,
    SearchDependencyUnavailable,
)
from research_platform.search.contracts import (
    RetrievalMode,
    SearchFilters,
    SearchOperation,
    SearchRequest,
    SearchResultStatus,
)
from research_platform.search.paper_reads import PaperIdentityConflict, SnapshotNotFound
from research_platform.tools.fakes import (
    FakeCorpus,
    FakeDiscoveryService,
    FakePaper,
    FakePassage,
    FakeServices,
    fake_services,
)
from research_platform.tools.research_tools import (
    ResearchTools,
    ToolContext,
    ToolLedger,
)

SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000001")
RUN_ID = UUID("00000000-0000-0000-0000-000000000002")
PROFILE_ID = "sha256:" + "a" * 64
PAPER_A = "W100"
PAPER_B = "W200"
PAPER_C = "W300"


def _corpus() -> FakeCorpus:
    return FakeCorpus(
        snapshot_id=SNAPSHOT_ID,
        papers=(
            FakePaper(PAPER_A, "Retrieval paper A", 2021),
            FakePaper(PAPER_B, "Retrieval paper B", 2023),
            FakePaper(PAPER_C, "Other paper C", 2024),
        ),
        passages=(
            FakePassage("chunk-a1", PAPER_A, "Hybrid retrieval improves recall."),
            FakePassage("chunk-a2", PAPER_A, "Dense retrieval baseline."),
            FakePassage("chunk-b1", PAPER_B, "Hybrid retrieval supports evidence."),
            FakePassage("chunk-c1", PAPER_C, "Unrelated ranking result."),
        ),
        citations=(
            (PAPER_A, PAPER_B),
            (PAPER_B, PAPER_C),
            (PAPER_C, PAPER_A),
            (PAPER_C, PAPER_B),
        ),
    )


def _context(
    *,
    filters: ResearchFilters | None = None,
    budgets: RunBudgets | None = None,
    mode: ResearchMode = ResearchMode.QUICK,
    question: str = "What do recent retrieval studies find?",
) -> ToolContext:
    return ToolContext(
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        retrieval_profile_id=PROFILE_ID,
        mode=mode,
        question=question,
        filters=filters or ResearchFilters(),
        budgets=budgets or RunBudgets(),
    )


def _tools(
    corpus: FakeCorpus | None = None,
    *,
    discovery: FakeDiscoveryService | None = None,
) -> tuple[ResearchTools, FakeServices]:
    resolved = corpus or _corpus()
    services = FakeServices(resolved)
    return (
        ResearchTools(
            search=services,
            papers=services,
            citations=services,
            related=services,
            discovery=discovery,
        ),
        services,
    )


@pytest.mark.anyio
async def test_search_papers_builds_reranked_request_and_collects_supporting_evidence() -> (
    None
):
    tools, services = _tools()
    requests: list[SearchRequest] = []
    original = services.execute

    async def record(request: SearchRequest, *, request_id: str):
        requests.append(request)
        return await original(request, request_id=request_id)

    services.execute = record  # type: ignore[method-assign]
    observation, ledger = await tools.execute(
        SearchPapersAction(tool="search_papers", query="hybrid retrieval", limit=2),
        context=_context(),
        ledger=ToolLedger(),
    )

    assert observation.status == "succeeded"
    assert requests[0].mode is RetrievalMode.RERANKED
    assert requests[0].operation is SearchOperation.PAPER_SEARCH
    assert requests[0].snapshot_id == SNAPSHOT_ID
    assert requests[0].retrieval_profile_id == PROFILE_ID
    assert observation.summary["papers"][0]["paper_id"] == PAPER_A
    assert observation.evidence[0].text == "Hybrid retrieval improves recall."
    assert observation.evidence[0].title == "Retrieval paper A"
    assert ledger.tool_calls_used == 1


@pytest.mark.anyio
async def test_discover_returns_abstract_evidence() -> None:
    discovery = FakeDiscoveryService(
        (
            DiscoveredPaper(
                paper_id="W410",
                openalex_id="W410",
                title="A retrieval study",
                publication_year=2023,
                abstract="Synthetic abstract text.",
                similarity=0.91,
                catalog_status="metadata_only",
            ),
            DiscoveredPaper(
                paper_id="W420",
                openalex_id="W420",
                title="An ingested study",
                publication_year=2024,
                abstract=None,
                similarity=0.82,
                catalog_status="ingested",
            ),
        )
    )
    tools, _ = _tools(discovery=discovery)
    context = _context(
        mode=ResearchMode.DEEP_RESEARCH,
        question="Does reranking help retrieval?",
        filters=ResearchFilters(year_from=2022, year_to=2025),
    )

    observation, ledger = await tools.execute(
        DiscoverPapersAction(
            tool="discover_papers",
            query="reranking retrieval",
            year_from=2020,
            year_to=2030,
        ),
        context=context,
        ledger=ToolLedger(),
    )

    assert discovery.calls == [
        {
            "run_id": RUN_ID,
            "question": "Does reranking help retrieval?",
            "query": "reranking retrieval",
            "year_from": 2022,
            "year_to": 2025,
            "limit": 5,
        }
    ]
    assert observation.status == "succeeded"
    assert observation.summary["papers"] == [
        {
            "paper_id": "W410",
            "title": "A retrieval study",
            "publication_year": 2023,
            "catalog_status": "metadata_only",
            "similarity": 0.91,
        },
        {
            "paper_id": "W420",
            "title": "An ingested study",
            "publication_year": 2024,
            "catalog_status": "ingested",
            "similarity": 0.82,
        },
    ]
    assert "abstract" not in str(observation.summary)
    assert len(observation.evidence) == 1
    assert observation.evidence[0].model_dump() == {
        "chunk_id": "abstract:W410",
        "paper_id": "W410",
        "text": "Synthetic abstract text.",
        "title": "A retrieval study",
        "publication_year": 2023,
        "kind": "abstract",
        "source_location": {},
        "reranker_score": None,
    }
    assert ledger.tool_calls_used == 1


@pytest.mark.anyio
async def test_discovery_embedder_prepares_frozen_lexical_encoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_platform.api import app as api_app
    from research_platform.ingestion import sparse_build
    from research_platform.ingestion.generation_index import (
        GenerationIndexConfiguration,
        SparseLexicalSettings,
        SparseVector,
    )
    from research_platform.search import sparse_lexical

    lexical = SparseLexicalSettings(
        analyzer="scientific-en",
        analyzer_revision="v1",
        vocabulary_id="scientific-en-v1",
        k1=1.5,
        b=0.75,
        evidence_average_length=30.4,
        paper_average_length=180.2,
    )
    configuration = GenerationIndexConfiguration(
        passages_collection="test-passages",
        papers_collection="test-papers",
        embedding_model="model",
        embedding_revision="revision",
        preprocessing_revision="preprocessing",
        vector_size=2,
        distance="Cosine",
        batch_size=2,
        maximum_input_tokens=512,
        lexical=lexical,
    )
    pool = object()
    repositories: list[object] = []
    sparse_encoders: list[object] = []

    class FakeVocabularyRepository:
        def __init__(self, received_pool: object) -> None:
            repositories.append(received_pool)

    class FakeSparseEncoder:
        def __init__(self, vocabulary: object, settings: object) -> None:
            self.vocabulary = vocabulary
            self.settings = settings
            self.prepared = False
            self.encoded: tuple[str, ...] = ()
            sparse_encoders.append(self)

        async def prepare(self) -> None:
            self.prepared = True

        async def encode_papers(
            self, texts: tuple[str, ...] | list[str]
        ) -> tuple[tuple[SparseVector, tuple[str, ...]], ...]:
            self.encoded = tuple(texts)
            return ((SparseVector(indices=(1,), values=(0.5,)), ("retrieval",)),)

    class FakeDenseEmbedder:
        def __init__(self) -> None:
            self.encoded: tuple[str, ...] = ()

        async def embed(
            self, texts: tuple[str, ...] | list[str], *, configuration: object
        ) -> tuple[tuple[float, ...], ...]:
            self.encoded = tuple(texts)
            return ((0.1, 0.2),)

    monkeypatch.setattr(sparse_build, "SparseEncoder", FakeSparseEncoder)
    monkeypatch.setattr(
        sparse_lexical, "VocabularyRepository", FakeVocabularyRepository
    )
    dense = FakeDenseEmbedder()

    combined = await api_app._build_discovery_embedder(
        dense,
        pool,
        configuration,  # type: ignore[arg-type]
    )

    assert repositories == [pool]
    sparse = sparse_encoders[0]
    assert isinstance(sparse, FakeSparseEncoder)
    assert sparse.vocabulary is not None
    assert sparse.settings is lexical
    assert sparse.prepared
    assert await combined.embed(
        ["candidate abstract"], configuration=configuration.dense_configuration()
    ) == ((0.1, 0.2),)
    assert await combined.encode_papers(["Candidate title"]) == (
        (SparseVector(indices=(1,), values=(0.5,)), ("retrieval",)),
    )
    assert dense.encoded == ("candidate abstract",)
    assert sparse.encoded == ("Candidate title",)


@pytest.mark.anyio
async def test_discovery_service_assembles_composite_embedder_and_closes_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from research_platform.api import app as api_app
    from research_platform.config import DiscoverySettings, Settings
    from research_platform.discovery import online
    from research_platform.ingestion import catalog, generation_index, openalex
    from research_platform.ingestion.generation_index import (
        GenerationIndexConfiguration,
        SparseLexicalSettings,
    )

    configuration = GenerationIndexConfiguration(
        passages_collection="test-passages",
        papers_collection="test-papers",
        embedding_model="model",
        embedding_revision="revision",
        preprocessing_revision="preprocessing",
        vector_size=2,
        distance="Cosine",
        batch_size=2,
        maximum_input_tokens=512,
        lexical=SparseLexicalSettings(
            analyzer="scientific-en",
            analyzer_revision="v1",
            vocabulary_id="scientific-en-v1",
            k1=1.5,
            b=0.75,
            evidence_average_length=30.4,
            paper_average_length=180.2,
        ),
    )
    configuration_path = tmp_path / "generation.json"
    configuration_path.write_text(json.dumps(configuration.to_dict()), encoding="utf-8")
    pool = object()
    qdrant_http = object()
    dense_embedder = object()
    composite_embedder = object()
    api_key = "offline-test-key"
    build_calls: list[tuple[object, object, GenerationIndexConfiguration]] = []
    http_clients: list[FakeHTTPClient] = []
    openalex_clients: list[FakeOpenAlexClient] = []
    catalogs: list[FakeCatalogRepository] = []
    collections: list[FakeGenerationCollection] = []
    ledgers: list[FakeSpendLedger] = []
    services: list[FakeOnlineDiscovery] = []

    class FakeHTTPClient:
        def __init__(self, *, base_url: str, timeout: object) -> None:
            self.base_url = base_url
            self.timeout = timeout
            self.closed = False
            http_clients.append(self)

        async def __aenter__(self) -> FakeHTTPClient:
            return self

        async def __aexit__(self, *_exc_info: object) -> None:
            self.closed = True

    class FakeOpenAlexClient:
        def __init__(
            self, configuration: object, api_key: str, http: FakeHTTPClient
        ) -> None:
            self.configuration = configuration
            self.api_key = api_key
            self.http = http
            openalex_clients.append(self)

    class FakeCatalogRepository:
        def __init__(self, received_pool: object) -> None:
            self.pool = received_pool
            catalogs.append(self)

    class FakeGenerationCollection:
        def __init__(
            self,
            received_configuration: GenerationIndexConfiguration,
            collection: str,
            http: object,
        ) -> None:
            self.configuration = received_configuration
            self.collection = collection
            self.http = http
            collections.append(self)

    class FakeSpendLedger:
        def __init__(self, received_pool: object) -> None:
            self.pool = received_pool
            ledgers.append(self)

    class FakeOnlineDiscovery:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            services.append(self)

    async def build_embedder(
        dense: object,
        received_pool: object,
        received_configuration: GenerationIndexConfiguration,
    ) -> object:
        build_calls.append((dense, received_pool, received_configuration))
        return composite_embedder

    monkeypatch.setattr(api_app, "_build_discovery_embedder", build_embedder)
    monkeypatch.setattr(api_app.httpx, "AsyncClient", FakeHTTPClient)
    monkeypatch.setattr(online, "OnlineDiscovery", FakeOnlineDiscovery)
    monkeypatch.setattr(online, "SpendLedger", FakeSpendLedger)
    monkeypatch.setattr(catalog, "CatalogRepository", FakeCatalogRepository)
    monkeypatch.setattr(
        generation_index, "GenerationQdrantCollection", FakeGenerationCollection
    )
    monkeypatch.setattr(openalex, "OpenAlexClient", FakeOpenAlexClient)

    runtime = SimpleNamespace(pool=pool, http=qdrant_http, embedder=dense_embedder)
    settings = Settings(
        openalex_api_key=api_key,
        generation_configuration=configuration_path,
    )

    async with AsyncExitStack() as stack:
        discovery = await api_app._build_discovery_service(settings, runtime, stack)

    assert discovery is services[0]
    assert build_calls[0][0] is dense_embedder
    assert build_calls[0][1] is pool
    parsed_configuration = build_calls[0][2]
    assert parsed_configuration.to_dict() == configuration.to_dict()
    assert openalex_clients[0].api_key == api_key
    assert openalex_clients[0].http is http_clients[0]
    assert catalogs[0].pool is pool
    assert collections[0].configuration is parsed_configuration
    assert collections[0].collection == "papers"
    assert collections[0].http is qdrant_http
    assert ledgers[0].pool is pool
    assert services[0].kwargs["openalex"] is openalex_clients[0]
    assert services[0].kwargs["catalog"] is catalogs[0]
    assert services[0].kwargs["papers"] is collections[0]
    assert services[0].kwargs["embedder"] is composite_embedder
    assert services[0].kwargs["configuration"] is parsed_configuration
    assert services[0].kwargs["ledger"] is ledgers[0]
    assert services[0].kwargs["settings"] == DiscoverySettings()
    assert openalex_clients[0].configuration.year_range.start_year == 2020
    assert openalex_clients[0].configuration.year_range.end_year == 2100
    assert http_clients[0].closed

    disabled_settings = Settings(
        openalex_api_key=None,
        generation_configuration=configuration_path,
    )
    async with AsyncExitStack() as stack:
        disabled = await api_app._build_discovery_service(
            disabled_settings, runtime, stack
        )
    assert disabled is None

    missing_configuration_settings = Settings(
        openalex_api_key=api_key,
        generation_configuration=tmp_path / "missing-generation.json",
    )
    async with AsyncExitStack() as stack:
        missing_configuration = await api_app._build_discovery_service(
            missing_configuration_settings, runtime, stack
        )
    assert missing_configuration is None
    assert len(http_clients) == 1
    assert len(services) == 1


@pytest.mark.anyio
async def test_discover_rejected_in_quick_mode() -> None:
    discovery = FakeDiscoveryService()
    tools, _ = _tools(discovery=discovery)

    observation, ledger = await tools.execute(
        DiscoverPapersAction(tool="discover_papers", query="retrieval"),
        context=_context(),
        ledger=ToolLedger(),
    )

    assert observation.status == "rejected"
    assert observation.error_category == "mode_not_allowed"
    assert discovery.calls == []
    assert ledger.tool_calls_used == 0
    assert ledger.records == 1


@pytest.mark.anyio
async def test_discovery_budget_is_failed_observation() -> None:
    discovery = FakeDiscoveryService(
        budget_error=DiscoveryBudgetExceeded("run_search_limit")
    )
    tools, _ = _tools(discovery=discovery)

    observation, _ = await tools.execute(
        DiscoverPapersAction(tool="discover_papers", query="retrieval"),
        context=_context(mode=ResearchMode.DEEP_RESEARCH),
        ledger=ToolLedger(),
    )

    assert observation.status == "failed"
    assert observation.error_category == "discovery_budget"
    assert observation.retryable is False


@pytest.mark.anyio
async def test_discover_counts_against_tool_budget() -> None:
    discovery = FakeDiscoveryService(
        (
            DiscoveredPaper(
                paper_id="W410",
                openalex_id="W410",
                title="A retrieval study",
                publication_year=2023,
                abstract="Synthetic abstract text.",
                similarity=0.91,
                catalog_status="metadata_only",
            ),
        )
    )
    tools, _ = _tools(discovery=discovery)
    context = _context(
        mode=ResearchMode.DEEP_RESEARCH,
        budgets=RunBudgets(max_tool_calls=1),
    )
    discovered, ledger = await tools.execute(
        DiscoverPapersAction(tool="discover_papers", query="retrieval"),
        context=context,
        ledger=ToolLedger(),
    )
    rejected, ledger = await tools.execute(
        SearchEvidenceAction(tool="search_evidence", query="retrieval"),
        context=context,
        ledger=ledger,
    )

    assert discovered.status == "succeeded"
    assert rejected.status == "rejected"
    assert rejected.error_category == "budget_exhausted"
    assert ledger.tool_calls_used == 1


@pytest.mark.anyio
async def test_search_evidence_passes_paper_ids_and_years() -> None:
    tools, services = _tools()
    requests: list[SearchRequest] = []
    original = services.execute

    async def record(request: SearchRequest, *, request_id: str):
        requests.append(request)
        return await original(request, request_id=request_id)

    services.execute = record  # type: ignore[method-assign]
    observation, _ = await tools.execute(
        SearchEvidenceAction(
            tool="search_evidence",
            query="hybrid retrieval",
            paper_ids=(PAPER_B,),
            year_from=2020,
            year_to=2025,
        ),
        context=_context(filters=ResearchFilters(year_from=2022, year_to=2025)),
        ledger=ToolLedger(),
    )

    assert requests[0].operation is SearchOperation.EVIDENCE_SEARCH
    assert requests[0].filters.paper_ids == (PAPER_B,)
    assert (requests[0].filters.year_from, requests[0].filters.year_to) == (2022, 2025)
    assert observation.summary["chunks"][0]["paper_id"] == PAPER_B
    assert all(hit.paper_id == PAPER_B for hit in observation.evidence)


@pytest.mark.anyio
async def test_duplicate_action_is_served_from_cache_without_service_call() -> None:
    tools, services = _tools()
    action = SearchPapersAction(tool="search_papers", query="hybrid retrieval")
    first, ledger = await tools.execute(action, context=_context(), ledger=ToolLedger())
    original = services.execute

    async def unexpected(*args: object, **kwargs: object):
        raise AssertionError("cached calls must not reach search")

    services.execute = unexpected  # type: ignore[method-assign]
    second, ledger = await tools.execute(action, context=_context(), ledger=ledger)

    assert first.status == "succeeded"
    assert second.status == "cached"
    assert second.evidence == ()
    assert second.summary == first.summary
    assert ledger.tool_calls_used == 1
    assert ledger.records == 2
    services.execute = original  # type: ignore[method-assign]


@pytest.mark.anyio
async def test_budget_exhausted_rejects_without_service_call() -> None:
    tools, services = _tools()

    async def unexpected(*args: object, **kwargs: object):
        raise AssertionError("rejected calls must not reach search")

    services.execute = unexpected  # type: ignore[method-assign]
    observation, ledger = await tools.execute(
        SearchPapersAction(tool="search_papers", query="hybrid retrieval"),
        context=_context(budgets=RunBudgets(max_tool_calls=1)),
        ledger=ToolLedger(tool_calls_used=1),
    )

    assert observation.status == "rejected"
    assert observation.error_category == "budget_exhausted"
    assert ledger.tool_calls_used == 1
    assert ledger.records == 1


@pytest.mark.anyio
async def test_citation_depth_is_tracked_and_enforced() -> None:
    tools, _ = _tools()
    observation, ledger = await tools.execute(
        GetCitationsAction(tool="get_citations", paper_id=PAPER_A),
        context=_context(),
        ledger=ToolLedger(),
    )
    assert observation.status == "succeeded"
    assert ledger.paper_depths[PAPER_C] == 1

    _, ledger = await tools.execute(
        GetReferencesAction(tool="get_references", paper_id=PAPER_C),
        context=_context(),
        ledger=ledger,
    )
    assert ledger.paper_depths[PAPER_B] == 2

    rejected, ledger = await tools.execute(
        FindRelatedPapersAction(tool="find_related_papers", paper_id=PAPER_B),
        context=_context(),
        ledger=ledger,
    )
    assert rejected.status == "rejected"
    assert rejected.error_category == "citation_depth_exceeded"
    assert ledger.tool_calls_used == 2


@pytest.mark.anyio
async def test_year_filters_intersect_and_empty_range_is_rejected() -> None:
    tools, services = _tools()
    requests: list[SearchRequest] = []
    original = services.execute

    async def record(request: SearchRequest, *, request_id: str):
        requests.append(request)
        return await original(request, request_id=request_id)

    services.execute = record  # type: ignore[method-assign]
    observation, ledger = await tools.execute(
        SearchPapersAction(
            tool="search_papers", query="hybrid retrieval", year_from=2021, year_to=2025
        ),
        context=_context(filters=ResearchFilters(year_from=2022, year_to=2023)),
        ledger=ToolLedger(),
    )
    assert observation.status == "succeeded"
    assert (requests[0].filters.year_from, requests[0].filters.year_to) == (2022, 2023)

    empty, ledger = await tools.execute(
        SearchEvidenceAction(
            tool="search_evidence",
            query="hybrid retrieval",
            year_from=2019,
            year_to=2021,
        ),
        context=_context(filters=ResearchFilters(year_from=2022)),
        ledger=ledger,
    )
    assert empty.status == "rejected"
    assert empty.error_category == "empty_filter"
    assert len(requests) == 1
    assert ledger.tool_calls_used == 1


@pytest.mark.anyio
async def test_get_paper_citations_references_and_related_summaries() -> None:
    tools, _ = _tools()
    paper, ledger = await tools.execute(
        GetPaperAction(tool="get_paper", paper_id=PAPER_A),
        context=_context(),
        ledger=ToolLedger(),
    )
    assert paper.summary == {
        "paper_id": PAPER_A,
        "title": "Retrieval paper A",
        "year": 2021,
        "status": "in_snapshot",
    }

    citations, ledger = await tools.execute(
        GetCitationsAction(tool="get_citations", paper_id=PAPER_A),
        context=_context(),
        ledger=ledger,
    )
    assert citations.summary["edges"][0]["paper_id"] == PAPER_C
    assert citations.summary["coverage_note"]

    references, ledger = await tools.execute(
        GetReferencesAction(tool="get_references", paper_id=PAPER_A),
        context=_context(),
        ledger=ledger,
    )
    assert references.summary["edges"][0]["paper_id"] == PAPER_B

    related, _ = await tools.execute(
        FindRelatedPapersAction(tool="find_related_papers", paper_id=PAPER_A),
        context=_context(),
        ledger=ledger,
    )
    assert related.summary["papers"]
    assert related.summary["coverage_note"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "category", "retryable"),
    [
        (SearchDependencyUnavailable("unavailable"), "retrieval_error", True),
        (RetrievalExecutionFailure("failed"), "retrieval_error", True),
        (TimeoutError("late"), "retrieval_error", True),
        (SnapshotNotFound("missing"), "invalid_argument", False),
        (PaperIdentityConflict("ambiguous"), "invalid_argument", False),
        (IncompatibleRetrievalProfile("mismatch"), "invalid_argument", False),
        (ValueError("invalid"), "invalid_argument", False),
        (EvidenceAccessDenied("forbidden"), "access_denied", False),
    ],
)
async def test_service_errors_map_to_failed_observations(
    error: Exception, category: str, retryable: bool
) -> None:
    tools, services = _tools()

    async def fail(*args: object, **kwargs: object):
        raise error

    services.execute = fail  # type: ignore[method-assign]
    observation, ledger = await tools.execute(
        SearchPapersAction(tool="search_papers", query="hybrid retrieval"),
        context=_context(),
        ledger=ToolLedger(),
    )
    assert observation.status == "failed"
    assert observation.error_category == category
    assert observation.retryable is retryable
    assert ledger.tool_calls_used == 1


@pytest.mark.anyio
async def test_unexpected_exception_propagates() -> None:
    tools, services = _tools()

    async def fail(*args: object, **kwargs: object):
        raise RuntimeError("unexpected")

    services.execute = fail  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="unexpected"):
        await tools.execute(
            SearchPapersAction(tool="search_papers", query="hybrid retrieval"),
            context=_context(),
            ledger=ToolLedger(),
        )


@pytest.mark.anyio
async def test_ordinals_increase_for_every_call_including_rejected() -> None:
    tools, _ = _tools()
    first, ledger = await tools.execute(
        SearchPapersAction(tool="search_papers", query="hybrid retrieval"),
        context=_context(budgets=RunBudgets(max_tool_calls=1)),
        ledger=ToolLedger(),
    )
    rejected, ledger = await tools.execute(
        SearchEvidenceAction(tool="search_evidence", query="dense retrieval"),
        context=_context(budgets=RunBudgets(max_tool_calls=1)),
        ledger=ledger,
    )
    cached, ledger = await tools.execute(
        SearchPapersAction(tool="search_papers", query="hybrid retrieval"),
        context=_context(budgets=RunBudgets(max_tool_calls=1)),
        ledger=ledger,
    )
    assert (first.ordinal, rejected.ordinal, cached.ordinal) == (0, 1, 2)
    assert ledger.records == 3
    assert ledger.tool_calls_used == 1


@pytest.mark.anyio
async def test_summary_contains_no_passage_text() -> None:
    tools, _ = _tools()
    observation, _ = await tools.execute(
        SearchEvidenceAction(tool="search_evidence", query="hybrid retrieval"),
        context=_context(),
        ledger=ToolLedger(),
    )
    assert observation.evidence
    summary = str(observation.summary)
    assert all(hit.text not in summary for hit in observation.evidence)


@pytest.mark.anyio
async def test_fake_search_is_deterministic_and_filters_years() -> None:
    search, _, _, _ = fake_services(_corpus())
    request = SearchRequest(
        query="hybrid retrieval",
        snapshot_id=SNAPSHOT_ID,
        retrieval_profile_id=PROFILE_ID,
        mode=RetrievalMode.RERANKED,
        operation=SearchOperation.EVIDENCE_SEARCH,
        filters=SearchFilters(year_from=2022, year_to=2024),
        limit=10,
    )
    first = await search.execute(request, request_id="fake:0")
    second = await search.execute(request, request_id="fake:1")
    assert [hit.chunk_id for hit in first.hits] == [hit.chunk_id for hit in second.hits]
    assert [hit.chunk_id for hit in first.hits] == ["chunk-b1"]
    assert first.eligible_count == 2

    no_match_request = SearchRequest(
        query="zzzznotpresent",
        snapshot_id=SNAPSHOT_ID,
        retrieval_profile_id=PROFILE_ID,
        mode=RetrievalMode.RERANKED,
        operation=SearchOperation.EVIDENCE_SEARCH,
        filters=SearchFilters(year_from=2022, year_to=2024),
        limit=10,
    )
    no_match = await search.execute(no_match_request, request_id="fake:2")
    assert no_match.result_status is SearchResultStatus.NO_CANDIDATES_RETURNED

    failing_search, _, _, _ = fake_services(
        replace(_corpus(), failing_queries=frozenset({"fail"}))
    )
    with pytest.raises(SearchDependencyUnavailable):
        await failing_search.execute(
            replace(no_match_request, query="fail"),
            request_id="fake:3",
        )
