"""Transport coverage for the served retrieval identity."""

from __future__ import annotations

import asyncio
from uuid import UUID

import httpx
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.api.auth import AuthSettings
from research_platform.api.research_routes import ResearchAPIServices
from research_platform.auth.keys import InMemoryApiKeyStore
from research_platform.config import Settings
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.runner import ServingIdentity
from research_platform.services.readiness import ReadinessReport

_SNAPSHOT = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
_PROFILE = "sha256:" + "a" * 64


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


class StubExecutor:
    async def submit(self, _run_id: UUID, *, request_id: str | None = None) -> None:
        return None


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://test:test@localhost:5432/research_test",
        qdrant_url="http://localhost:26333",
    )


def _app(*, with_research_services: bool = True) -> FastAPI:
    services = (
        ResearchAPIServices(
            store=InMemoryRunStore(),
            executor=StubExecutor(),
            serving=ServingIdentity(_SNAPSHOT, _PROFILE, 1),
        )
        if with_research_services
        else None
    )
    return create_app(
        settings=_settings(),
        dependency_checker=StubReadinessChecker(),
        research_services=services,
    )


async def _request(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_serving_returns_the_identity() -> None:
    response = asyncio.run(_request(_app(), "/v1/serving"))

    assert response.status_code == 200
    assert response.json() == {
        "snapshot_id": str(_SNAPSHOT),
        "retrieval_profile_id": _PROFILE,
        "generation": 1,
    }


def test_serving_without_research_services_is_503() -> None:
    response = asyncio.run(_request(_app(with_research_services=False), "/v1/serving"))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_serving_requires_a_key_in_api_key_mode() -> None:
    app = create_app(
        settings=_settings(),
        dependency_checker=StubReadinessChecker(),
        auth_settings=AuthSettings(mode="api_key", bind_host="127.0.0.1"),
        api_key_store=InMemoryApiKeyStore(),
    )

    response = asyncio.run(_request(app, "/v1/serving"))

    assert response.status_code == 401


def test_serving_is_in_the_openapi_schema() -> None:
    assert "/v1/serving" in _app().openapi()["paths"]
