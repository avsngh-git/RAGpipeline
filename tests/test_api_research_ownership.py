"""Run ownership behavior for the research API."""

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
from research_platform.runs.contracts import ResearchRequest
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.runner import ServingIdentity
from research_platform.services.readiness import ReadinessReport

_SNAPSHOT = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


class StubExecutor:
    async def submit(self, _run_id: UUID, *, request_id: str | None = None) -> None:
        return None


def _app(
    store: InMemoryRunStore,
    *,
    auth_mode: AuthMode = "api_key",
    api_key_store: InMemoryApiKeyStore | None = None,
) -> FastAPI:
    return create_app(
        settings=Settings(
            environment="test",
            database_url="postgresql://test:test@localhost:5432/research_test",
            qdrant_url="http://localhost:26333",
        ),
        dependency_checker=StubReadinessChecker(),
        research_services=ResearchAPIServices(
            store=store,
            executor=StubExecutor(),  # type: ignore[arg-type]
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
    return store, {"alice": alice, "bob": bob, "ops": ops}


def _body() -> dict[str, object]:
    return {"question": "A synthetic research question", "mode": "quick"}


def test_owner_reads_own_run() -> None:
    async def exercise() -> httpx.Response:
        keys_store, keys = await _keys()
        app = _app(InMemoryRunStore(), api_key_store=keys_store)
        created = await _request(
            app, "POST", "/v1/research", key=keys["alice"], body=_body()
        )
        return await _request(
            app, "GET", f"/v1/research/{created.json()['run_id']}", key=keys["alice"]
        )

    assert asyncio.run(exercise()).status_code == 200


def test_other_principal_gets_404() -> None:
    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        keys_store, keys = await _keys()
        app = _app(InMemoryRunStore(), api_key_store=keys_store)
        created = await _request(
            app, "POST", "/v1/research", key=keys["alice"], body=_body()
        )
        foreign = await _request(
            app, "GET", f"/v1/research/{created.json()['run_id']}", key=keys["bob"]
        )
        missing = await _request(
            app,
            "GET",
            "/v1/research/00000000-0000-4000-8000-000000000001",
            key=keys["bob"],
        )
        return foreign, missing

    foreign, missing = asyncio.run(exercise())

    assert foreign.status_code == missing.status_code == 404
    foreign_error = foreign.json()["error"]
    missing_error = missing.json()["error"]
    assert {
        key: value for key, value in foreign_error.items() if key != "request_id"
    } == {key: value for key, value in missing_error.items() if key != "request_id"}


def test_admin_reads_any_run() -> None:
    async def exercise() -> httpx.Response:
        keys_store, keys = await _keys()
        app = _app(InMemoryRunStore(), api_key_store=keys_store)
        created = await _request(
            app, "POST", "/v1/research", key=keys["alice"], body=_body()
        )
        return await _request(
            app, "GET", f"/v1/research/{created.json()['run_id']}", key=keys["ops"]
        )

    assert asyncio.run(exercise()).status_code == 200


def test_legacy_run_visible_to_admin_only() -> None:
    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        keys_store, keys = await _keys()
        run_store = InMemoryRunStore()
        run_id = await run_store.create_run(
            ResearchRequest(question="Legacy run", mode="quick")
        )
        app = _app(run_store, api_key_store=keys_store)
        path = f"/v1/research/{run_id}"
        return (
            await _request(app, "GET", path, key=keys["alice"]),
            await _request(app, "GET", path, key=keys["ops"]),
        )

    owner, admin = asyncio.run(exercise())

    assert owner.status_code == 404
    assert admin.status_code == 200


def test_disabled_mode_local_principal_reads_all() -> None:
    async def exercise() -> httpx.Response:
        run_store = InMemoryRunStore()
        run_id = await run_store.create_run(
            ResearchRequest(question="Owned by another principal", mode="quick"),
            principal="alice",
        )
        app = _app(run_store, auth_mode="disabled")
        return await _request(app, "GET", f"/v1/research/{run_id}")

    assert asyncio.run(exercise()).status_code == 200


def test_created_run_records_principal() -> None:
    async def exercise() -> str:
        keys_store, keys = await _keys()
        run_store = InMemoryRunStore()
        app = _app(run_store, api_key_store=keys_store)
        created = await _request(
            app, "POST", "/v1/research", key=keys["alice"], body=_body()
        )
        # The response contains the new ID; the store records the authenticated owner.
        run_id = UUID(created.json()["run_id"])
        return (await run_store.get_run(run_id)).principal

    assert asyncio.run(exercise()) == "alice"
