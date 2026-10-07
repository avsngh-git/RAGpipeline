"""HTTP authentication behavior for versioned API routes."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.api.auth import AuthMode, AuthSettings
from research_platform.api.research_routes import ResearchAPIServices
from research_platform.auth.keys import InMemoryApiKeyStore, Scope
from research_platform.config import Settings
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


def _settings(environment: str = "test") -> Settings:
    return Settings(
        environment=environment,
        database_url="postgresql://test:test@localhost:5432/research_test",
        qdrant_url="http://localhost:26333",
    )


def _app(
    *,
    auth_mode: AuthMode = "api_key",
    api_key_store: InMemoryApiKeyStore | None = None,
    services: ResearchAPIServices | None = None,
    environment: str = "test",
    bind_host: str = "127.0.0.1",
) -> FastAPI:
    return create_app(
        settings=_settings(environment),
        dependency_checker=StubReadinessChecker(),
        research_services=services,
        auth_settings=AuthSettings(mode=auth_mode, bind_host=bind_host),
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


async def _key(
    store: InMemoryApiKeyStore, scopes: tuple[Scope, ...]
) -> tuple[UUID, str]:
    record, plain_key = await store.create("test-client", scopes)
    return record.key_id, plain_key


def _research_services() -> ResearchAPIServices:
    return ResearchAPIServices(
        store=InMemoryRunStore(),
        executor=StubExecutor(),  # type: ignore[arg-type]
        serving=ServingIdentity(_SNAPSHOT, "profile-v1"),
    )


def _research_body() -> dict[str, object]:
    return {"question": "A synthetic research question", "mode": "quick"}


def test_missing_key_is_401_with_challenge() -> None:
    response = asyncio.run(
        _request(_app(), "POST", "/v1/research", body=_research_body())
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.headers["www-authenticate"] == "Bearer"


def test_auth_settings_default_by_environment() -> None:
    assert AuthSettings.from_env("test", {}).mode == "disabled"
    assert AuthSettings.from_env("development", {}).mode == "api_key"


def test_auth_settings_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="RESEARCH_PLATFORM_AUTH_MODE"):
        AuthSettings.from_env("test", {"RESEARCH_PLATFORM_AUTH_MODE": "off"})


def test_invalid_key_is_401() -> None:
    response = asyncio.run(
        _request(
            _app(api_key_store=InMemoryApiKeyStore()),
            "POST",
            "/v1/research",
            key="zq7731",
            body=_research_body(),
        )
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"
    assert response.headers["www-authenticate"] == "Bearer"


def test_revoked_key_is_401() -> None:
    async def exercise() -> httpx.Response:
        store = InMemoryApiKeyStore()
        key_id, key = await _key(store, (Scope.RESEARCH,))
        assert await store.revoke(key_id)
        return await _request(
            _app(api_key_store=store),
            "POST",
            "/v1/research",
            key=key,
            body=_research_body(),
        )

    response = asyncio.run(exercise())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_read_key_cannot_start_research() -> None:
    async def exercise() -> httpx.Response:
        store = InMemoryApiKeyStore()
        _, key = await _key(store, (Scope.READ,))
        return await _request(
            _app(api_key_store=store),
            "POST",
            "/v1/research",
            key=key,
            body=_research_body(),
        )

    response = asyncio.run(exercise())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"


def test_research_key_can_start_research() -> None:
    async def exercise() -> httpx.Response:
        store = InMemoryApiKeyStore()
        _, key = await _key(store, (Scope.RESEARCH,))
        return await _request(
            _app(api_key_store=store, services=_research_services()),
            "POST",
            "/v1/research",
            key=key,
            body=_research_body(),
        )

    response = asyncio.run(exercise())

    assert response.status_code == 202


def test_admin_key_has_every_scope() -> None:
    async def exercise() -> tuple[bool, ...]:
        store = InMemoryApiKeyStore()
        _, key = await _key(store, (Scope.ADMIN,))
        principal = await store.authenticate(key)
        assert principal is not None
        return tuple(principal.has(scope) for scope in Scope)

    assert asyncio.run(exercise()) == (True, True, True, True)


def test_ingest_requires_ingest_scope() -> None:
    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        store = InMemoryApiKeyStore()
        _, read_key = await _key(store, (Scope.READ,))
        _, ingest_key = await _key(store, (Scope.INGEST,))
        path = f"/v1/collections/{uuid4()}/ingest"
        body = {"paper_ids": ["W123"]}
        app = _app(api_key_store=store)
        denied = await _request(app, "POST", path, key=read_key, body=body)
        allowed = await _request(app, "POST", path, key=ingest_key, body=body)
        return denied, allowed

    denied, allowed = asyncio.run(exercise())

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "insufficient_scope"
    assert allowed.status_code == 503
    assert allowed.json()["error"]["code"] == "service_unavailable"


def test_public_endpoints_need_no_key() -> None:
    app = _app()

    responses = tuple(
        asyncio.run(_request(app, "GET", path))
        for path in ("/health", "/ready", "/metrics", "/openapi.json")
    )

    assert tuple(response.status_code for response in responses) == (200, 200, 200, 200)


def test_disabled_mode_allows_requests() -> None:
    response = asyncio.run(
        _request(
            _app(auth_mode="disabled", services=_research_services()),
            "POST",
            "/v1/research",
            body=_research_body(),
        )
    )

    assert response.status_code == 202


def test_disabled_mode_rejected_in_production() -> None:
    with pytest.raises(
        ValueError,
        match="auth mode disabled is allowed only for loopback development or tests",
    ):
        _app(auth_mode="disabled", environment="production")


def test_disabled_mode_rejected_off_loopback() -> None:
    with pytest.raises(
        ValueError,
        match="auth mode disabled is allowed only for loopback development or tests",
    ):
        _app(auth_mode="disabled", bind_host="0.0.0.0")


def test_error_body_has_no_key() -> None:
    key = "zq7731"
    response = asyncio.run(
        _request(
            _app(api_key_store=InMemoryApiKeyStore()),
            "POST",
            "/v1/research",
            key=key,
            body=_research_body(),
        )
    )

    assert response.status_code == 401
    assert key not in response.text
