"""Research API run cancellation coverage."""

from __future__ import annotations

import asyncio
from uuid import UUID

import httpx
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.api.auth import AuthMode, AuthSettings
from research_platform.api.research_routes import ResearchAPIServices
from research_platform.auth.keys import InMemoryApiKeyStore, Scope
from research_platform.config import Settings
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.contracts import (
    AnswerOutcome,
    FailureCategory,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunProvenance,
    RunUsage,
)
from research_platform.runs.diagnosis import (
    DiagnosisStage,
    diagnose,
    load_diagnosis_inputs,
)
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.repository import ToolCallRecord
from research_platform.runs.runner import ServingIdentity
from research_platform.services.readiness import ReadinessReport

_SNAPSHOT = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


class StubExecutor:
    def __init__(self) -> None:
        self.cancelled: list[UUID] = []

    async def submit(self, _run_id: UUID, *, request_id: str | None = None) -> None:
        return None

    async def cancel(self, run_id: UUID) -> None:
        self.cancelled.append(run_id)


def _app(
    store: InMemoryRunStore,
    executor: StubExecutor,
    *,
    api_key_store: InMemoryApiKeyStore,
    auth_mode: AuthMode = "api_key",
) -> FastAPI:
    return create_app(
        settings=Settings(
            environment="test",
            database_url="postgresql://test:test@localhost:5432/research_test",
            qdrant_url="http://localhost:26333",
        ),
        dependency_checker=StubReadinessChecker(),  # type: ignore[arg-type]
        research_services=ResearchAPIServices(
            store=store,
            executor=executor,  # type: ignore[arg-type]
            serving=ServingIdentity(_SNAPSHOT, "profile-v1"),
        ),
        auth_settings=AuthSettings(mode=auth_mode, bind_host="127.0.0.1"),
        api_key_store=api_key_store,
    )


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    key: str | None = None,
    body: dict[str, object] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    headers = {} if key is None else {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=body, headers=headers)


async def _keys() -> tuple[InMemoryApiKeyStore, dict[str, str]]:
    store = InMemoryApiKeyStore()
    _, alice = await store.create("alice", (Scope.RESEARCH, Scope.READ))
    _, bob = await store.create("bob", (Scope.RESEARCH, Scope.READ))
    _, ops = await store.create("ops", (Scope.ADMIN,))
    _, reader = await store.create("reader", (Scope.READ,))
    return store, {"alice": alice, "bob": bob, "ops": ops, "reader": reader}


def _body() -> dict[str, object]:
    return {"question": "Synthetic cancellation question", "mode": "quick"}


async def _start(app: FastAPI, key: str) -> tuple[httpx.Response, str]:
    response = await _request(app, "POST", "/v1/research", key=key, body=_body())
    return response, response.json()["run_id"]


def test_cancel_queued_run() -> None:
    async def exercise() -> tuple[httpx.Response, StubExecutor, str]:
        keys_store, keys = await _keys()
        executor = StubExecutor()
        app = _app(InMemoryRunStore(), executor, api_key_store=keys_store)
        _, run_id = await _start(app, keys["alice"])
        response = await _request(
            app, "POST", f"/v1/research/{run_id}/cancel", key=keys["alice"]
        )
        return response, executor, run_id

    response, executor, run_id = asyncio.run(exercise())
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["failure_category"] == "cancelled_by_principal"
    assert executor.cancelled == [UUID(run_id)]


def test_cancel_frees_active_slot() -> None:
    async def exercise() -> tuple[int, int, int]:
        keys_store, keys = await _keys()
        app = _app(InMemoryRunStore(), StubExecutor(), api_key_store=keys_store)
        _, first_id = await _start(app, keys["alice"])
        await _start(app, keys["alice"])
        full = await _request(
            app, "POST", "/v1/research", key=keys["alice"], body=_body()
        )
        cancelled = await _request(
            app, "POST", f"/v1/research/{first_id}/cancel", key=keys["alice"]
        )
        after = await _request(
            app, "POST", "/v1/research", key=keys["alice"], body=_body()
        )
        return full.status_code, cancelled.status_code, after.status_code

    assert asyncio.run(exercise()) == (429, 200, 202)


def test_cancel_keeps_partial_record() -> None:
    async def exercise() -> tuple[httpx.Response, int]:
        keys_store, keys = await _keys()
        store = InMemoryRunStore()
        app = _app(store, StubExecutor(), api_key_store=keys_store)
        _, run_id = await _start(app, keys["alice"])
        identifier = UUID(run_id)
        await store.append_tool_call(
            identifier,
            ToolCallRecord(
                ordinal=1,
                tool_name="search_papers",
                arguments={"query": "zq7731"},
                status="succeeded",
                result_summary={"count": 1},
                duration_ms=5.0,
            ),
        )
        response = await _request(
            app, "POST", f"/v1/research/{run_id}/cancel", key=keys["alice"]
        )
        calls = await store.list_tool_calls(identifier)
        return response, len(calls)

    response, calls = asyncio.run(exercise())
    assert response.status_code == 200
    assert calls == 1
    assert response.json()["usage"]["tool_calls"] == 1


def test_cancel_finished_run_is_409() -> None:
    async def exercise() -> httpx.Response:
        keys_store, keys = await _keys()
        store = InMemoryRunStore()
        executor = StubExecutor()
        app = _app(store, executor, api_key_store=keys_store)
        _, run_id = await _start(app, keys["alice"])
        identifier = UUID(run_id)
        provenance = RunProvenance(
            snapshot_id=_SNAPSHOT,
            retrieval_profile_id="profile-v1",
            configuration_id=f"sha256:{'b' * 64}",
            code_revision="test-revision",
            model=ModelIdentity(name="qwen", runtime="ollama", context_tokens=8192),
            thinking={CallKind.PLAN: False},
            prompt_versions={},
            budgets=RunBudgets(),
            trace_id="trace-test",
        )
        await store.mark_running(identifier, provenance=provenance)
        await store.complete_run(
            identifier,
            answer="Synthetic answer",
            outcome=AnswerOutcome.ANSWERED,
            claims=(),
            usage=RunUsage(),
        )
        return await _request(
            app, "POST", f"/v1/research/{run_id}/cancel", key=keys["alice"]
        )

    response = asyncio.run(exercise())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "run_not_active"


def test_cancel_other_principals_run_is_404() -> None:
    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        keys_store, keys = await _keys()
        app = _app(InMemoryRunStore(), StubExecutor(), api_key_store=keys_store)
        _, run_id = await _start(app, keys["alice"])
        path = f"/v1/research/{run_id}/cancel"
        return (
            await _request(app, "POST", path, key=keys["bob"]),
            await _request(app, "POST", path, key=keys["ops"]),
        )

    foreign, admin = asyncio.run(exercise())
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "run_not_found"
    assert admin.status_code == 200


def test_cancel_requires_research_scope() -> None:
    async def exercise() -> httpx.Response:
        keys_store, keys = await _keys()
        app = _app(InMemoryRunStore(), StubExecutor(), api_key_store=keys_store)
        _, run_id = await _start(app, keys["alice"])
        return await _request(
            app, "POST", f"/v1/research/{run_id}/cancel", key=keys["reader"]
        )

    response = asyncio.run(exercise())
    assert response.status_code == 403


def test_diagnosis_of_cancelled_run() -> None:
    async def exercise() -> tuple[DiagnosisStage, tuple[str, ...], tuple[str, ...]]:
        store = InMemoryRunStore()
        run_id = await store.create_run(
            ResearchRequest(
                question="Synthetic cancellation question", mode=ResearchMode.QUICK
            )
        )
        await store.fail_run(
            run_id,
            category=FailureCategory.CANCELLED_BY_PRINCIPAL,
            message="cancelled_by_principal",
            usage=RunUsage(),
        )
        result = diagnose(await load_diagnosis_inputs(store, run_id))
        return (
            result.stage,
            tuple(finding.code for finding in result.findings),
            tuple(
                finding.detail
                for finding in result.findings
                if finding.code == "cancelled_by_principal"
            ),
        )

    stage, findings, details = asyncio.run(exercise())
    assert stage is DiagnosisStage.NONE
    assert "cancelled_by_principal" in findings
    assert details == ("0 tool calls, 0 model calls recorded",)
