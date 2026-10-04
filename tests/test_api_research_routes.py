"""Transport coverage for starting and reading research runs."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI

from research_platform.api import app as app_module
from research_platform.api import create_app
from research_platform.api.research_routes import ResearchAPIServices
from research_platform.api.routes import Phase2APIServices
from research_platform.config import Settings
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimResult,
    EvidenceCitation,
    FailureCategory,
    ResearchMode,
    ResearchRequest,
    ResearchRunView,
    RunStatus,
    RunUsage,
    SupportLabel,
)
from research_platform.runs.executor import ResearchQueueFull
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.repository import EvidenceRecord
from research_platform.runs.runner import ServingIdentity
from research_platform.services.readiness import ReadinessReport

_SNAPSHOT = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
_FOREIGN_SNAPSHOT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


class StubExecutor:
    def __init__(self, *, full: bool = False) -> None:
        self.full = full
        self.submissions: list[UUID] = []

    async def submit(self, run_id: UUID) -> None:
        if self.full:
            raise ResearchQueueFull("synthetic queue full")
        self.submissions.append(run_id)


class PassageFreeViewStore(InMemoryRunStore):
    async def get_run_view(self, run_id: UUID) -> ResearchRunView:
        stored = self._runs[run_id]
        return ResearchRunView(
            run_id=run_id,
            status=RunStatus.COMPLETED,
            mode=ResearchMode.QUICK,
            question="A synthetic research question",
            answer="A synthetic claim [E1].",
            answer_outcome=AnswerOutcome.ANSWERED,
            claims=(
                ClaimResult(
                    claim_id="claim-1",
                    text="A synthetic claim.",
                    evidence=(
                        EvidenceCitation(
                            handle="E1", chunk_id="chunk-1", paper_id="W123"
                        ),
                    ),
                    support=SupportLabel.SUPPORTED,
                ),
            ),
            failure_category=None,
            provenance=None,
            usage=RunUsage(),
            created_at=stored.created_at,
        )


class _TrackedResource:
    def __init__(self, label: str, events: list[str]) -> None:
        self.label = label
        self.events = events

    async def __aenter__(self) -> _TrackedResource:
        self.events.append(f"open:{self.label}")
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.events.append(f"close:{self.label}")


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://test:test@localhost:5432/research_test",
        qdrant_url="http://localhost:26333",
    )


def _app(
    *,
    store: InMemoryRunStore | None = None,
    executor: StubExecutor | None = None,
    serving: ServingIdentity | None = None,
) -> tuple[FastAPI, InMemoryRunStore, StubExecutor]:
    active_store = store or InMemoryRunStore()
    active_executor = executor or StubExecutor()
    app = create_app(
        settings=_settings(),
        dependency_checker=StubReadinessChecker(),
        research_services=ResearchAPIServices(
            store=active_store,
            executor=active_executor,  # type: ignore[arg-type]
            serving=serving or ServingIdentity(_SNAPSHOT, "profile-v1"),
        ),
    )
    return app, active_store, active_executor


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


def _body(*, snapshot_id: UUID | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "question": "A synthetic research question",
        "mode": "quick",
    }
    if snapshot_id is not None:
        body["snapshot_id"] = str(snapshot_id)
    return body


def test_post_returns_202_queued_view_and_submits() -> None:
    app, store, executor = _app()

    response = asyncio.run(_request(app, "POST", "/v1/research", body=_body()))

    assert response.status_code == 202
    run_id = UUID(response.json()["run_id"])
    assert response.json()["status"] == "queued"
    assert (asyncio.run(store.get_run(run_id))).status is RunStatus.QUEUED
    assert executor.submissions == [run_id]


def test_post_rejects_foreign_snapshot_with_409() -> None:
    app, store, executor = _app()

    response = asyncio.run(
        _request(
            app,
            "POST",
            "/v1/research",
            body=_body(snapshot_id=_FOREIGN_SNAPSHOT),
        )
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "incompatible_snapshot"
    assert not store._runs
    assert executor.submissions == []


def test_post_validation_errors_are_422() -> None:
    app, _, _ = _app()

    response = asyncio.run(
        _request(
            app,
            "POST",
            "/v1/research",
            body={"question": "x", "mode": "unknown"},
        )
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_post_queue_full_is_503_and_run_failed() -> None:
    app, store, executor = _app(executor=StubExecutor(full=True))

    response = asyncio.run(_request(app, "POST", "/v1/research", body=_body()))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "research_queue_full"
    failed = next(iter(store._runs.values()))
    view = asyncio.run(store.get_run_view(failed.run_id))
    assert view.status is RunStatus.FAILED
    assert view.failure_category is FailureCategory.INTERNAL
    assert view.error_message == "queue_full"
    assert executor.submissions == []


def test_get_returns_view_and_404_for_unknown() -> None:
    app, store, _ = _app()
    run_id = asyncio.run(store.create_run(ResearchRequest.model_validate(_body())))

    found = asyncio.run(_request(app, "GET", f"/v1/research/{run_id}"))
    missing = asyncio.run(_request(app, "GET", f"/v1/research/{uuid4()}"))

    assert found.status_code == 200
    assert found.json()["run_id"] == str(run_id)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "run_not_found"


def test_routes_503_without_services() -> None:
    app = create_app(settings=_settings(), dependency_checker=StubReadinessChecker())

    response = asyncio.run(_request(app, "POST", "/v1/research", body=_body()))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_response_has_no_passage_text() -> None:
    async def exercise() -> tuple[httpx.Response, UUID]:
        store = PassageFreeViewStore()
        run_id = await store.create_run(ResearchRequest.model_validate(_body()))
        await store.save_evidence(
            run_id,
            (
                EvidenceRecord(
                    handle="E1",
                    chunk_id="chunk-1",
                    paper_id="W123",
                    text="passage text that must stay private",
                    metadata={"title": "Synthetic paper", "publication_year": 2024},
                ),
            ),
        )
        app, _, _ = _app(store=store)
        response = await _request(app, "GET", f"/v1/research/{run_id}")
        return response, run_id

    response, run_id = asyncio.run(exercise())

    assert response.status_code == 200
    assert response.json()["run_id"] == str(run_id)
    assert "passage text that must stay private" not in response.text
    assert response.json()["claims"][0]["evidence"][0] == {
        "handle": "E1",
        "chunk_id": "chunk-1",
        "paper_id": "W123",
    }


def test_research_startup_failure_closes_partial_resources_and_keeps_phase2(
    monkeypatch, caplog
) -> None:
    async def exercise() -> tuple[dict[str, object], int, bool, list[str]]:
        events: list[str] = []
        phase2_services = Phase2APIServices(search=object())
        runtime = SimpleNamespace(
            api_services=phase2_services,
            close=lambda: _append_async(events, "phase2"),
        )

        async def create_phase2_runtime(_settings: Settings) -> object:
            return runtime

        async def fail_research_runtime(
            _settings: Settings, _runtime: object, stack
        ) -> ResearchAPIServices:
            await stack.enter_async_context(_TrackedResource("partial", events))
            raise RuntimeError("synthetic private run text")

        monkeypatch.setattr(
            "research_platform.search.application.create_phase2_runtime",
            create_phase2_runtime,
            raising=False,
        )
        monkeypatch.setattr(
            app_module, "_build_research_services", fail_research_runtime
        )
        app = create_app(
            settings=Settings(environment="development"),
            dependency_checker=StubReadinessChecker(),
        )

        async with app.router.lifespan_context(app):
            ready = await _request(app, "GET", "/ready")
            health = await _request(app, "GET", "/health")
            assert app.state.phase2_services is phase2_services
            return ready.json(), health.status_code, runtime is not None, events

    caplog.set_level(logging.ERROR)
    ready, health_status, runtime_created, events = asyncio.run(exercise())

    assert ready == {
        "status": "not_ready",
        "dependencies": {
            "postgres": "ok",
            "qdrant": "ok",
            "phase2_search": "ok",
            "research_runs": "unavailable",
        },
    }
    assert health_status == 200
    assert runtime_created
    assert events == ["open:partial", "close:partial", "phase2"]
    assert any(
        record.getMessage() == "research_runtime_unavailable"
        and record.error_type == "RuntimeError"
        for record in caplog.records
    )
    assert "synthetic private run text" not in caplog.text


def test_lifespan_stops_executor_and_closes_research_before_phase2(monkeypatch) -> None:
    async def exercise() -> list[str]:
        events: list[str] = []
        runtime = SimpleNamespace(
            api_services=Phase2APIServices(),
            close=lambda: _append_async(events, "phase2"),
        )

        async def create_phase2_runtime(_settings: Settings) -> object:
            return runtime

        async def build_research_runtime(
            _settings: Settings, _runtime: object, stack
        ) -> ResearchAPIServices:
            await stack.enter_async_context(_TrackedResource("llm-client", events))
            await stack.enter_async_context(_TrackedResource("checkpointer", events))

            async def stop_executor() -> None:
                events.append("stop:executor")

            stack.push_async_callback(stop_executor)
            return ResearchAPIServices(
                store=InMemoryRunStore(),
                executor=StubExecutor(),  # type: ignore[arg-type]
                serving=ServingIdentity(_SNAPSHOT, "profile-v1"),
            )

        monkeypatch.setattr(
            "research_platform.search.application.create_phase2_runtime",
            create_phase2_runtime,
            raising=False,
        )
        monkeypatch.setattr(
            app_module, "_build_research_services", build_research_runtime
        )
        app = create_app(
            settings=Settings(environment="development"),
            dependency_checker=StubReadinessChecker(),
        )
        async with app.router.lifespan_context(app):
            ready = await _request(app, "GET", "/ready")
            assert ready.status_code == 200
        return events

    assert asyncio.run(exercise()) == [
        "open:llm-client",
        "open:checkpointer",
        "stop:executor",
        "close:checkpointer",
        "close:llm-client",
        "phase2",
    ]


async def _append_async(events: list[str], label: str) -> None:
    events.append(label)


def test_post_pins_the_served_generation() -> None:
    app, store, _executor = _app(
        serving=ServingIdentity(_SNAPSHOT, "profile-v1", generation=3)
    )
    response = asyncio.run(_request(app, "POST", "/v1/research", body=_body()))

    assert response.status_code == 202
    assert list(store.generations.values()) == [3]
