"""Research run use cases shared by transports."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.api.auth import AuthSettings
from research_platform.api.research_routes import ResearchAPIServices
from research_platform.auth.keys import (
    LOCAL_PRINCIPAL,
    InMemoryApiKeyStore,
    Principal,
    Scope,
)
from research_platform.config import Settings
from research_platform.runs.contracts import (
    FailureCategory,
    ResearchMode,
    ResearchRequest,
    RunStatus,
    RunUsage,
)
from research_platform.runs.executor import ResearchQueueFull
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.runner import ServingIdentity
from research_platform.services.capabilities import ResearchCapabilities
from research_platform.services.errors import AppError
from research_platform.services.readiness import ReadinessReport

SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
FOREIGN_SNAPSHOT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class StubExecutor:
    def __init__(self, *, full: bool = False) -> None:
        self.full = full
        self.submissions: list[tuple[UUID, str | None]] = []

    async def submit(self, run_id: UUID, *, request_id: str | None = None) -> None:
        if self.full:
            raise ResearchQueueFull("synthetic queue full")
        self.submissions.append((run_id, request_id))


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://test:test@localhost:5432/research_test",
        qdrant_url="http://localhost:26333",
    )


def _services(
    store: InMemoryRunStore | None = None,
    executor: StubExecutor | None = None,
) -> tuple[ResearchAPIServices, InMemoryRunStore, StubExecutor]:
    active_store = store or InMemoryRunStore()
    active_executor = executor or StubExecutor()
    services = ResearchAPIServices(
        store=active_store,
        executor=active_executor,  # type: ignore[arg-type]
        serving=ServingIdentity(SNAPSHOT_ID, "profile-v1", generation=3),
    )
    return services, active_store, active_executor


def _capabilities(
    services: ResearchAPIServices | None = None,
    *,
    max_active_runs: int = 2,
) -> ResearchCapabilities:
    return ResearchCapabilities(
        settings=_settings(),
        phase2=None,
        research=services,
        max_active_runs_per_principal=max_active_runs,
    )


def _request(snapshot_id: UUID | None = None) -> ResearchRequest:
    return ResearchRequest(
        question="A synthetic research question",
        mode=ResearchMode.QUICK,
        snapshot_id=snapshot_id,
    )


def _call_start(
    capabilities: ResearchCapabilities,
    principal: Principal,
    *,
    request: ResearchRequest | None = None,
):
    return asyncio.run(
        capabilities.start_run(
            request or _request(), principal=principal, request_id="request-123"
        )
    )


def test_start_run_records_principal_and_generation() -> None:
    services, store, executor = _services()
    principal = Principal("test-client", frozenset({Scope.RESEARCH}))

    view = _call_start(_capabilities(services), principal)
    stored = asyncio.run(store.get_run(view.run_id))

    assert stored.principal == "test-client"
    assert store.generations[view.run_id] == 3
    assert executor.submissions == [(view.run_id, "request-123")]


def test_research_key_without_ingest_records_no_ingestion() -> None:
    services, store, _ = _services()
    principal = Principal("research-only", frozenset({Scope.RESEARCH}))

    view = _call_start(_capabilities(services), principal)

    assert asyncio.run(store.get_run(view.run_id)).ingestion_permitted is False


def test_ingest_or_admin_records_ingestion_permitted() -> None:
    for principal in (
        Principal("ingest-client", frozenset({Scope.RESEARCH, Scope.INGEST})),
        Principal("admin-client", frozenset({Scope.ADMIN})),
        LOCAL_PRINCIPAL,
    ):
        services, store, _ = _services()
        view = _call_start(_capabilities(services), principal)
        assert asyncio.run(store.get_run(view.run_id)).ingestion_permitted is True


def test_start_run_rejects_a_foreign_snapshot() -> None:
    services, store, executor = _services()

    with pytest.raises(AppError) as raised:
        _call_start(
            _capabilities(services),
            Principal("test-client", frozenset({Scope.RESEARCH})),
            request=_request(FOREIGN_SNAPSHOT_ID),
        )

    assert raised.value.status_code == 409
    assert raised.value.code == "incompatible_snapshot"
    assert not store._runs
    assert not executor.submissions


def test_active_run_limit_is_429_with_retry_after() -> None:
    services, store, _ = _services()
    principal = Principal("test-client", frozenset({Scope.RESEARCH}))
    asyncio.run(store.create_run(_request(), principal=principal.name))

    with pytest.raises(AppError) as raised:
        _call_start(_capabilities(services, max_active_runs=1), principal)

    assert raised.value.status_code == 429
    assert raised.value.code == "too_many_active_runs"
    assert raised.value.headers == {"Retry-After": "30"}


def test_queue_full_fails_the_run_and_is_503() -> None:
    services, store, _ = _services(executor=StubExecutor(full=True))

    with pytest.raises(AppError) as raised:
        _call_start(
            _capabilities(services),
            Principal("test-client", frozenset({Scope.RESEARCH})),
        )

    assert raised.value.status_code == 503
    assert raised.value.code == "research_queue_full"
    run_id = next(iter(store._runs))
    stored = asyncio.run(store.get_run(run_id))
    assert stored.status is RunStatus.FAILED
    view = asyncio.run(store.get_run_view(run_id))
    assert view.failure_category is FailureCategory.INTERNAL
    assert view.error_message == "queue_full"
    assert view.usage == RunUsage.model_construct()


def test_get_run_hides_other_principals_runs() -> None:
    services, store, _ = _services()
    run_id = asyncio.run(store.create_run(_request(), principal="owner"))

    with pytest.raises(AppError) as raised:
        asyncio.run(
            _capabilities(services).get_run(
                run_id, principal=Principal("other", frozenset({Scope.READ}))
            )
        )

    assert raised.value.status_code == 404
    assert raised.value.code == "run_not_found"
    admin_view = asyncio.run(
        _capabilities(services).get_run(
            run_id, principal=Principal("admin", frozenset({Scope.ADMIN}))
        )
    )
    assert admin_view.run_id == run_id


def test_resolve_snapshot_defaults_to_the_served_snapshot() -> None:
    services, _, _ = _services()
    capabilities = _capabilities(services)

    assert capabilities.resolve_snapshot(None) == services.serving
    assert capabilities.resolve_snapshot(SNAPSHOT_ID) == services.serving
    with pytest.raises(AppError) as raised:
        capabilities.resolve_snapshot(FOREIGN_SNAPSHOT_ID)
    assert raised.value.status_code == 409
    assert raised.value.code == "incompatible_snapshot"


def test_missing_research_services_is_503() -> None:
    capabilities = _capabilities()
    principal = Principal("test-client", frozenset({Scope.RESEARCH}))

    with pytest.raises(AppError) as serving_error:
        capabilities.serving()
    with pytest.raises(AppError) as start_error:
        _call_start(capabilities, principal)
    with pytest.raises(AppError) as read_error:
        asyncio.run(capabilities.get_run(uuid4(), principal=principal))

    for raised in (serving_error, start_error, read_error):
        assert raised.value.status_code == 503
        assert raised.value.code == "service_unavailable"


def test_from_app_state_reads_settings_and_services() -> None:
    services, _, _ = _services()
    rate_limit_settings = SimpleNamespace(max_active_runs_per_principal=7)
    state = SimpleNamespace(
        settings=_settings(),
        phase2_services=None,
        research_services=services,
        rate_limit_settings=rate_limit_settings,
    )

    capabilities = ResearchCapabilities.from_app_state(state)

    assert capabilities.settings is state.settings
    assert capabilities.research is services
    assert capabilities.max_active_runs_per_principal == 7
    without_rate_limits = ResearchCapabilities.from_app_state(
        SimpleNamespace(settings=_settings())
    )
    assert without_rate_limits.max_active_runs_per_principal == 2


async def _http_request(
    app: FastAPI, key: str, body: dict[str, object]
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/v1/research",
            json=body,
            headers={"Authorization": f"Bearer {key}"},
        )


def test_http_research_key_without_ingest_records_no_ingestion() -> None:
    async def exercise() -> tuple[httpx.Response, InMemoryRunStore]:
        key_store = InMemoryApiKeyStore()
        _, key = await key_store.create("research-only", (Scope.RESEARCH,))
        services, store, _ = _services()
        app = create_app(
            settings=_settings(),
            dependency_checker=StubReadinessChecker(),
            research_services=services,
            auth_settings=AuthSettings(mode="api_key", bind_host="127.0.0.1"),
            api_key_store=key_store,
        )
        response = await _http_request(
            app, key, {"question": "A synthetic research question", "mode": "quick"}
        )
        return response, store

    response, store = asyncio.run(exercise())

    assert response.status_code == 202
    run_id = UUID(response.json()["run_id"])
    assert asyncio.run(store.get_run(run_id)).ingestion_permitted is False
