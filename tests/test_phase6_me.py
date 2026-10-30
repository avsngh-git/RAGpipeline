"""Caller identity, readiness and model-probe contracts."""

from __future__ import annotations

import asyncio
from uuid import UUID

import httpx
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.api.auth import AuthSettings
from research_platform.api.research_routes import ResearchAPIServices
from research_platform.auth.keys import InMemoryApiKeyStore, Scope
from research_platform.config import Settings
from research_platform.llm.probe import OllamaProbe
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.runner import ServingIdentity
from research_platform.services.readiness import ReadinessReport


class _Readiness:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


class _Executor:
    async def submit(self, _run_id, *, request_id: str | None = None) -> None:
        return None


async def _keys() -> tuple[InMemoryApiKeyStore, dict[str, str]]:
    store = InMemoryApiKeyStore()
    _, alice = await store.create("alice", (Scope.READ, Scope.RESEARCH))
    _, reader = await store.create("reader", (Scope.READ,))
    return store, {"alice": alice, "reader": reader}


def _app(
    *,
    api_key_store: InMemoryApiKeyStore,
    llm_available=None,
    settings: Settings | None = None,
    with_research: bool = True,
) -> FastAPI:
    services = (
        ResearchAPIServices(
            store=InMemoryRunStore(),
            executor=_Executor(),  # type: ignore[arg-type]
            serving=ServingIdentity(
                UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c"), "profile-v1"
            ),
            llm_available=llm_available,
        )
        if with_research
        else None
    )
    return create_app(
        settings=settings
        or Settings(
            environment="test",
            database_url="postgresql://test:test@localhost:5432/research_test",
            qdrant_url="http://localhost:26333",
        ),
        dependency_checker=_Readiness(),
        research_services=services,
        auth_settings=AuthSettings(mode="api_key", bind_host="127.0.0.1"),
        api_key_store=api_key_store,
    )


async def _get_me(app: FastAPI, key: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/v1/me", headers={"Authorization": f"Bearer {key}"})


def test_me_reports_principal_and_scopes() -> None:
    async def exercise():
        keys_store, keys = await _keys()
        app = _app(api_key_store=keys_store, llm_available=_yes)
        return await _get_me(app, keys["alice"])

    payload = asyncio.run(exercise()).json()
    assert payload["principal"] == "alice"
    assert payload["scopes"] == ["read", "research"]


async def _yes() -> bool:
    return True


def test_me_runs_available_when_probe_true() -> None:
    async def exercise():
        keys_store, keys = await _keys()
        app = _app(api_key_store=keys_store, llm_available=_yes)
        return await _get_me(app, keys["alice"])

    assert asyncio.run(exercise()).json()["research_runs"] == "available"


def test_me_model_unreachable_when_probe_false_or_raises() -> None:
    async def no() -> bool:
        return False

    async def raising() -> bool:
        raise RuntimeError("synthetic probe failure")

    async def exercise():
        keys_store, keys = await _keys()
        results = []
        for probe in (no, raising, None):
            app = _app(api_key_store=keys_store, llm_available=probe)
            results.append(await _get_me(app, keys["alice"]))
        return results

    assert [
        response.json()["research_runs"] for response in asyncio.run(exercise())
    ] == [
        "model_unreachable",
        "model_unreachable",
        "model_unreachable",
    ]


def test_me_no_research_scope() -> None:
    async def exercise():
        keys_store, keys = await _keys()
        app = _app(api_key_store=keys_store, llm_available=_yes)
        return await _get_me(app, keys["reader"])

    assert asyncio.run(exercise()).json()["research_runs"] == "no_research_scope"


def test_me_service_unavailable_without_research_services() -> None:
    async def exercise():
        keys_store, keys = await _keys()
        app = _app(api_key_store=keys_store, with_research=False)
        return await _get_me(app, keys["alice"])

    assert asyncio.run(exercise()).json()["research_runs"] == "service_unavailable"


def test_me_reports_evidence_text_and_langfuse_url() -> None:
    async def exercise():
        keys_store, keys = await _keys()
        settings = Settings(
            environment="test",
            database_url="postgresql://test:test@localhost:5432/research_test",
            qdrant_url="http://localhost:26333",
            evidence_access_profile="trusted_private_local",
            langfuse_ui_url="http://127.0.0.1:3000/project/p1/traces",
        )
        app = _app(api_key_store=keys_store, llm_available=_yes, settings=settings)
        return await _get_me(app, keys["alice"])

    payload = asyncio.run(exercise()).json()
    assert payload["evidence_text"] is True
    assert payload["langfuse_ui_url"] == "http://127.0.0.1:3000/project/p1/traces"


def test_ollama_probe_matches_model_and_caches() -> None:
    async def exercise():
        now = [10.0]
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                json={"models": [{"name": "qwen3.5:2b"}]},
                request=request,
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://ollama"
        ) as client:
            probe = OllamaProbe(
                client, model="qwen3.5:2b", ttl_seconds=15, clock=lambda: now[0]
            )
            first = await probe()
            second = await probe()
            first_calls = calls
            now[0] += 16
            third = await probe()
        return first, second, third, first_calls, calls

    first, second, third, first_calls, calls = asyncio.run(exercise())
    assert first is second is third is True
    assert first_calls == 1 and calls == 2


def test_ollama_probe_false_on_missing_model_and_http_error() -> None:
    async def exercise():
        async def missing(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"models": []}, request=request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(missing), base_url="http://ollama"
        ) as client:
            missing_result = await OllamaProbe(client, model="qwen3.5:2b")()

        async def failure(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("synthetic connection failure")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(failure), base_url="http://ollama"
        ) as client:
            error_result = await OllamaProbe(client, model="qwen3.5:2b")()
        return missing_result, error_result

    assert asyncio.run(exercise()) == (False, False)


def test_langfuse_ui_url_setting(monkeypatch) -> None:
    monkeypatch.setenv(
        "RESEARCH_PLATFORM_LANGFUSE_UI_URL",
        "http://127.0.0.1:3000/project/p1/traces/",
    )
    assert Settings().langfuse_ui_url == "http://127.0.0.1:3000/project/p1/traces"
    monkeypatch.setenv("RESEARCH_PLATFORM_LANGFUSE_UI_URL", "")
    assert Settings().langfuse_ui_url is None
    monkeypatch.setenv("RESEARCH_PLATFORM_LANGFUSE_UI_URL", "ftp://x")
    try:
        Settings()
    except ValueError:
        pass
    else:
        raise AssertionError("unsupported Langfuse URL scheme was accepted")
