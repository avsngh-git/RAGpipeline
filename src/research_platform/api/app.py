"""FastAPI application construction and core health/search routes."""

import json
import logging
from collections.abc import Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

from research_platform.config import Settings
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    SparseVector,
)
from research_platform.ingestion.indexing import IndexConfiguration, VectorEmbedder
from research_platform.ingestion.paper_index import SparsePaperEncoder
from research_platform.observability.logging_config import configure_logging
from research_platform.observability.request_context import RequestIDMiddleware
from research_platform.observability.request_logging import RequestLoggingMiddleware
from research_platform.services.readiness import (
    LiveDependencyChecker,
    ReadinessChecker,
    ReadinessReport,
)
from research_platform.tools.research_tools import DiscoveryService

from .errors import AppError, handle_app_error, handle_unexpected_error
from .research_routes import ResearchAPIServices, create_research_router
from .routes import Phase2APIServices, create_phase2_router

logger = logging.getLogger("research_platform.api")

if TYPE_CHECKING:
    from research_platform.search.paper_similarity import PaperSimilarityReader


class _DiscoveryEmbedder:
    """Combine the runtime dense embedder with the frozen paper sparse encoder."""

    def __init__(self, dense: VectorEmbedder, sparse: SparsePaperEncoder) -> None:
        self._dense = dense
        self._sparse = sparse

    async def embed(
        self,
        texts: Sequence[str],
        *,
        configuration: IndexConfiguration,
    ) -> Sequence[Sequence[float]]:
        return await self._dense.embed(texts, configuration=configuration)

    async def encode_papers(
        self, texts: Sequence[str]
    ) -> tuple[tuple[SparseVector, tuple[str, ...]], ...]:
        return await self._sparse.encode_papers(texts)


async def _build_discovery_embedder(
    dense: VectorEmbedder,
    pool: Any,
    configuration: GenerationIndexConfiguration,
) -> VectorEmbedder:
    """Attach sparse encoding using the lexical settings frozen with this generation."""
    if configuration.lexical is None:
        return dense

    from research_platform.ingestion.sparse_build import SparseEncoder
    from research_platform.search.sparse_lexical import VocabularyRepository

    sparse = SparseEncoder(VocabularyRepository(pool), configuration.lexical)
    await sparse.prepare()
    return _DiscoveryEmbedder(dense, sparse)


class HealthResponse(BaseModel):
    """Response returned by the process liveness endpoint."""

    status: Literal["ok"]


class ReadyResponse(BaseModel):
    """Response returned by dependency readiness checks."""

    status: Literal["ready", "not_ready"]
    dependencies: dict[str, Literal["ok", "unavailable"]]


def create_app(
    settings: Settings | None = None,
    dependency_checker: ReadinessChecker | None = None,
    api_services: Phase2APIServices | None = None,
    research_services: ResearchAPIServices | None = None,
) -> FastAPI:
    """Create the HTTP application with health and Phase 2 routes."""
    settings = settings or Settings()
    configure_logging(settings.log_level)
    dependency_checker = dependency_checker or LiveDependencyChecker(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            runtime: Any | None = None
            application.state.phase2_runtime_ready = (
                True if api_services is not None else None
            )
            application.state.research_runtime_ready = (
                True if research_services is not None else None
            )
            application.state.phase2_services = api_services
            application.state.research_services = research_services

            if api_services is None and settings.environment != "test":
                try:
                    from research_platform.search.application import (
                        create_phase2_runtime,
                    )

                    runtime = await create_phase2_runtime(settings)
                    stack.push_async_callback(runtime.close)
                    application.state.phase2_services = runtime.api_services
                    application.state.phase2_runtime_ready = True
                except Exception as error:
                    runtime = None
                    application.state.phase2_services = None
                    application.state.phase2_runtime_ready = False
                    logger.error(
                        "phase2_runtime_unavailable",
                        extra={"error_type": type(error).__name__},
                    )

            if research_services is None:
                if runtime is not None and settings.environment != "test":
                    research_stack = AsyncExitStack()
                    try:
                        await research_stack.__aenter__()
                        application.state.research_services = (
                            await _build_research_services(
                                settings, runtime, research_stack
                            )
                        )
                    except Exception as error:
                        await research_stack.aclose()
                        application.state.research_services = None
                        application.state.research_runtime_ready = False
                        logger.error(
                            "research_runtime_unavailable",
                            extra={"error_type": type(error).__name__},
                        )
                    except BaseException:
                        await research_stack.aclose()
                        raise
                    else:
                        stack.push_async_callback(research_stack.aclose)
                        application.state.research_runtime_ready = True
                else:
                    application.state.research_services = None
                    if runtime is not None:
                        application.state.research_runtime_ready = False
            yield

    app = FastAPI(
        title="Scientific Research Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.phase2_services = api_services
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(Exception, handle_unexpected_error)

    async def handle_validation_error(request: Request, _exc: Exception) -> Response:
        return await handle_app_error(
            request,
            AppError("invalid_request", "Request validation failed.", 422),
        )

    app.add_exception_handler(RequestValidationError, handle_validation_error)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=ReadyResponse)
    async def ready(response: Response) -> ReadyResponse:
        report: ReadinessReport = await dependency_checker.check()
        dependencies: dict[str, Literal["ok", "unavailable"]] = {
            name: "ok" if available else "unavailable"
            for name, available in report.dependencies.items()
        }
        runtime_ready = getattr(app.state, "phase2_runtime_ready", None)
        if runtime_ready is False:
            dependencies["phase2_search"] = "unavailable"
        elif runtime_ready is True and api_services is None:
            dependencies["phase2_search"] = "ok"
        research_ready = getattr(app.state, "research_runtime_ready", None)
        if research_ready is False:
            dependencies["research_runs"] = "unavailable"
        elif research_ready is True:
            dependencies["research_runs"] = "ok"
        ready_status = all(value == "ok" for value in dependencies.values())
        if not ready_status:
            response.status_code = 503
        return ReadyResponse(
            status="ready" if ready_status else "not_ready",
            dependencies=dependencies,
        )

    app.include_router(create_phase2_router(settings, api_services))
    app.include_router(create_research_router(research_services))
    return app


async def _build_research_services(
    settings: Settings, runtime: Any, stack: AsyncExitStack
) -> ResearchAPIServices:
    """Compose and start the lifespan-owned research run runtime."""
    from research_platform.agents.graph_deep import build_deep_graph
    from research_platform.agents.graph_quick import build_quick_graph
    from research_platform.config import DiscoverySettings
    from research_platform.ingestion.provenance import code_revision
    from research_platform.llm.ollama import OllamaClient
    from research_platform.runs.checkpointing import open_checkpointer
    from research_platform.runs.contracts import ResearchMode, RunBudgets
    from research_platform.runs.executor import RunExecutor
    from research_platform.runs.repository import RunRepository
    from research_platform.runs.runner import (
        ResearchRunner,
        RunnerDependencies,
        resolve_serving_identity,
    )
    from research_platform.search.paper_related import RelatedPaperReader
    from research_platform.tools.research_tools import ResearchTools

    phase2_services = runtime.api_services
    if not isinstance(phase2_services, Phase2APIServices):
        raise RuntimeError("Phase 2 API services are unavailable")
    if (
        phase2_services.search is None
        or phase2_services.papers is None
        or phase2_services.citations is None
    ):
        raise RuntimeError("Phase 2 API services are incomplete")

    store = RunRepository(runtime.pool)
    related = RelatedPaperReader(runtime.pool)
    discovery = await _build_discovery_service(settings, runtime, stack)
    similarity = _build_similarity_reader(settings, runtime)
    ingestion = await _build_membership_policy(settings, runtime)
    tools = ResearchTools(
        search=phase2_services.search,
        papers=phase2_services.papers,
        citations=phase2_services.citations,
        related=related,
        discovery=discovery,
        similarity=similarity,
        ingestion=ingestion,
    )
    llm_http = await stack.enter_async_context(
        httpx.AsyncClient(
            base_url=settings.llm_base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.llm_timeout_seconds),
        )
    )
    llm = OllamaClient.from_settings(llm_http, settings)
    checkpointer = await stack.enter_async_context(
        open_checkpointer(settings.database_url)
    )
    serving = await resolve_serving_identity(settings, runtime.pool)
    runner = ResearchRunner(
        RunnerDependencies(
            repository=store,
            tools=tools,
            llm=llm,
            checkpointer=checkpointer,
            serving=serving,
            thinking=settings.llm_thinking,
            budgets=RunBudgets.model_validate(
                {"max_papers_per_wait": DiscoverySettings().max_papers_per_wait}
            ),
            code_revision=code_revision(),
            graphs={
                ResearchMode.QUICK: build_quick_graph,
                ResearchMode.DEEP_RESEARCH: build_deep_graph,
            },
        )
    )
    executor = RunExecutor(runner, store)
    stack.push_async_callback(executor.stop)
    await executor.start()
    return ResearchAPIServices(store=store, executor=executor, serving=serving)


def _build_similarity_reader(
    settings: Settings, runtime: Any
) -> "PaperSimilarityReader | None":
    """Use the configured paper catalog even when online discovery is disabled."""
    if not settings.generation_configuration.is_file():
        return None
    from research_platform.ingestion.generation_index import GenerationQdrantCollection
    from research_platform.search.paper_similarity import PaperSimilarityReader

    raw = json.loads(settings.generation_configuration.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("generation index configuration must be an object")
    configuration = GenerationIndexConfiguration.from_dict(raw)
    return PaperSimilarityReader(
        GenerationQdrantCollection(configuration, "papers", runtime.http),
        runtime.embedder,
    )


async def _build_membership_policy(settings: Settings, runtime: Any) -> Any:
    """Build the ingestion membership policy for the configured generation."""
    if not settings.generation_configuration.is_file():
        return None

    from research_platform.config import DiscoverySettings
    from research_platform.ingestion.generation_index import (
        GenerationIndexConfiguration,
        GenerationQdrantCollection,
    )
    from research_platform.ingestion.generation_registry import GenerationRegistry
    from research_platform.ingestion.membership_policy import MembershipPolicy

    raw = json.loads(settings.generation_configuration.read_text(encoding="utf-8"))
    configuration = GenerationIndexConfiguration.from_dict(raw)
    collection_id = await GenerationRegistry(runtime.pool).ensure_collection(
        settings.generation_collection
    )
    return MembershipPolicy(
        runtime.pool,
        GenerationQdrantCollection(configuration, "papers", runtime.http),
        DiscoverySettings(),
        collection_id=collection_id,
    )


async def _build_discovery_service(
    settings: Settings, runtime: Any, stack: AsyncExitStack
) -> DiscoveryService | None:
    """Build discovery when its key and published-generation config are available."""
    if (
        settings.openalex_api_key is None
        or not settings.generation_configuration.is_file()
    ):
        return None

    from research_platform.config import DiscoverySettings
    from research_platform.discovery.online import OnlineDiscovery, SpendLedger
    from research_platform.ingestion.catalog import CatalogRepository
    from research_platform.ingestion.config import (
        DiscoveryConfig,
        DiscoveryLimits,
        YearRange,
    )
    from research_platform.ingestion.generation_index import (
        GenerationIndexConfiguration,
        GenerationQdrantCollection,
    )
    from research_platform.ingestion.openalex import OPENALEX_API_BASE, OpenAlexClient

    raw_configuration = json.loads(
        settings.generation_configuration.read_text(encoding="utf-8")
    )
    if not isinstance(raw_configuration, dict):
        raise RuntimeError("generation index configuration must be an object")
    configuration = GenerationIndexConfiguration.from_dict(raw_configuration)
    discovery_embedder = await _build_discovery_embedder(
        runtime.embedder, runtime.pool, configuration
    )
    discovery_settings = DiscoverySettings()
    discovery_configuration = DiscoveryConfig(
        queries=("deep research",),
        year_range=YearRange(start_year=2020, end_year=2100),
        limits=DiscoveryLimits(
            per_page=discovery_settings.results_per_request,
            max_pages_per_query=discovery_settings.max_search_requests_per_run,
            max_total_requests=discovery_settings.max_search_requests_per_run,
            max_retries=2,
            timeout_seconds=15.0,
            minimum_request_interval_seconds=1.0,
        ),
    )
    openalex_http = await stack.enter_async_context(
        httpx.AsyncClient(
            base_url=OPENALEX_API_BASE,
            timeout=httpx.Timeout(15.0),
        )
    )
    openalex = OpenAlexClient(
        discovery_configuration,
        settings.openalex_api_key,
        openalex_http,
    )
    return OnlineDiscovery(
        openalex=openalex,
        catalog=CatalogRepository(runtime.pool),
        papers=GenerationQdrantCollection(configuration, "papers", runtime.http),
        embedder=discovery_embedder,
        configuration=configuration,
        ledger=SpendLedger(runtime.pool),
        settings=discovery_settings,
    )
