"""Scripted attacks against the authenticated HTTP boundary."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.api.auth import AuthSettings
from research_platform.api.rate_limits import (
    DEFAULT_LIMITS,
    Limit,
    RateLimitSettings,
    RouteClass,
)
from research_platform.api.research_routes import ResearchAPIServices
from research_platform.auth.keys import InMemoryApiKeyStore, Scope
from research_platform.config import Settings
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.runner import ServingIdentity
from research_platform.services.readiness import ReadinessReport

_SNAPSHOT = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
_KEY = "zq7731"


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


class StubExecutor:
    async def submit(self, _run_id: UUID, *, request_id: str | None = None) -> None:
        return None


def _app(
    *,
    store: InMemoryRunStore | None = None,
    key_store: InMemoryApiKeyStore | None = None,
    rate_limits: RateLimitSettings | None = None,
) -> FastAPI:
    run_store = store or InMemoryRunStore()
    return create_app(
        settings=Settings(
            environment="test",
            database_url="postgresql://test:test@localhost:5432/research_test",
            qdrant_url="http://localhost:26333",
        ),
        dependency_checker=StubReadinessChecker(),
        research_services=ResearchAPIServices(
            store=run_store,
            executor=StubExecutor(),  # type: ignore[arg-type]
            serving=ServingIdentity(_SNAPSHOT, "profile-v1"),
        ),
        auth_settings=AuthSettings(mode="api_key", bind_host="127.0.0.1"),
        api_key_store=key_store,
        rate_limit_settings=rate_limits,
    )


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    key: str | None = None,
    authorization: str | None = None,
    body: dict[str, object] | None = None,
    content: bytes | None = None,
) -> httpx.Response:
    headers = {} if key is None else {"Authorization": f"Bearer {key}"}
    if authorization is not None:
        headers["Authorization"] = authorization
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(
            method, path, headers=headers, json=body, content=content
        )


async def _keys() -> tuple[InMemoryApiKeyStore, dict[str, str]]:
    store = InMemoryApiKeyStore()
    _, alice = await store.create("alice", (Scope.RESEARCH, Scope.READ, Scope.INGEST))
    _, bob = await store.create("bob", (Scope.RESEARCH, Scope.READ, Scope.INGEST))
    _, read = await store.create("reader", (Scope.READ,))
    return store, {"alice": alice, "bob": bob, "read": read}


def _body(question: str = "Synthetic security test question") -> dict[str, object]:
    return {"question": question, "mode": "quick"}


@pytest.mark.anyio
async def test_no_key() -> None:
    response = await _request(_app(), "POST", "/v1/research", body=_body())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.anyio
async def test_basic_scheme_rejected() -> None:
    response = await _request(
        _app(), "POST", "/v1/research", authorization="Basic abc", body=_body()
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.anyio
async def test_key_with_whitespace_or_case_change() -> None:
    store = InMemoryApiKeyStore()
    _, key = await store.create("client", (Scope.RESEARCH,))
    response = await _request(
        _app(key_store=store), "POST", "/v1/research", key=key.upper(), body=_body()
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


@pytest.mark.anyio
async def test_revoked_key() -> None:
    store = InMemoryApiKeyStore()
    record, key = await store.create("client", (Scope.RESEARCH,))
    assert await store.revoke(record.key_id)
    response = await _request(
        _app(key_store=store), "POST", "/v1/research", key=key, body=_body()
    )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_read_scope_cannot_research() -> None:
    store = InMemoryApiKeyStore()
    _, key = await store.create("reader", (Scope.READ,))
    response = await _request(
        _app(key_store=store), "POST", "/v1/research", key=key, body=_body()
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"


@pytest.mark.anyio
async def test_read_scope_cannot_ingest() -> None:
    store = InMemoryApiKeyStore()
    _, key = await store.create("reader", (Scope.READ,))
    response = await _request(
        _app(key_store=store),
        "POST",
        f"/v1/collections/{uuid4()}/ingest",
        key=key,
        body={"paper_ids": ["W123"]},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"


@pytest.mark.anyio
async def test_cross_principal_run_read() -> None:
    store, keys = await _keys()
    app = _app(key_store=store)
    created = await _request(
        app, "POST", "/v1/research", key=keys["alice"], body=_body()
    )
    response = await _request(
        app, "GET", f"/v1/research/{created.json()['run_id']}", key=keys["bob"]
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"


@pytest.mark.anyio
async def test_run_id_probe_same_as_missing() -> None:
    store, keys = await _keys()
    app = _app(key_store=store)
    created = await _request(
        app, "POST", "/v1/research", key=keys["alice"], body=_body()
    )
    foreign = await _request(
        app, "GET", f"/v1/research/{created.json()['run_id']}", key=keys["bob"]
    )
    random_id = await _request(app, "GET", f"/v1/research/{uuid4()}", key=keys["bob"])

    assert (foreign.status_code, foreign.json()["error"]["code"]) == (
        random_id.status_code,
        random_id.json()["error"]["code"],
    )


@pytest.mark.anyio
async def test_question_too_long() -> None:
    store = InMemoryApiKeyStore()
    _, key = await store.create("client", (Scope.RESEARCH,))
    response = await _request(
        _app(key_store=store),
        "POST",
        "/v1/research",
        key=key,
        body=_body("q" * 2001),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.anyio
async def test_body_too_large() -> None:
    store = InMemoryApiKeyStore()
    _, key = await store.create("client", (Scope.RESEARCH,))
    payload = b'{"question":"' + b"x" * (70 * 1024) + b'","mode":"quick"}'
    response = await _request(
        _app(key_store=store),
        "POST",
        "/v1/research",
        key=key,
        content=payload,
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


async def _hostile_paper_id(app: FastAPI, key: str, path: str) -> httpx.Response:
    return await _request(app, "GET", path, key=key)


@pytest.mark.anyio
async def test_path_traversal_paper_id() -> None:
    store = InMemoryApiKeyStore()
    _, key = await store.create("reader", (Scope.READ,))
    response = await _hostile_paper_id(
        _app(key_store=store), key, "/v1/papers/..%2F..%2Fetc%2Fpasswd"
    )

    assert response.status_code in (404, 422)


@pytest.mark.anyio
async def test_sql_like_paper_id() -> None:
    store = InMemoryApiKeyStore()
    _, key = await store.create("reader", (Scope.READ,))
    response = await _hostile_paper_id(
        _app(key_store=store), key, "/v1/papers/W1'%20OR%201=1"
    )

    assert response.status_code in (404, 422)


@pytest.mark.anyio
async def test_rate_abuse() -> None:
    store = InMemoryApiKeyStore()
    _, key = await store.create("client", (Scope.RESEARCH,))
    settings = RateLimitSettings(
        {**DEFAULT_LIMITS, RouteClass.RESEARCH_CREATE: Limit(20, 3600)},
        max_active_runs_per_principal=100,
    )
    app = _app(key_store=store, rate_limits=settings)
    responses = [
        await _request(app, "POST", "/v1/research", key=key, body=_body())
        for _ in range(21)
    ]

    assert responses[-1].status_code == 429
    assert responses[-1].headers.get("retry-after") is not None


@pytest.mark.anyio
async def test_errors_hide_internals() -> None:
    store, keys = await _keys()
    app = _app(key_store=store)
    revoked_record, revoked_key = await store.create("revoked", (Scope.RESEARCH,))
    assert await store.revoke(revoked_record.key_id)
    created = await _request(
        app, "POST", "/v1/research", key=keys["alice"], body=_body()
    )
    run_path = f"/v1/research/{created.json()['run_id']}"
    collection_path = f"/v1/collections/{uuid4()}/ingest"
    errors = [
        await _request(app, "POST", "/v1/research", body=_body()),
        await _request(
            app, "POST", "/v1/research", authorization="Basic abc", body=_body()
        ),
        await _request(app, "POST", "/v1/research", key=_KEY, body=_body()),
        await _request(
            app, "POST", "/v1/research", key=keys["alice"].upper(), body=_body()
        ),
        await _request(app, "POST", "/v1/research", key=revoked_key, body=_body()),
        await _request(app, "POST", "/v1/research", key=keys["read"], body=_body()),
        await _request(
            app,
            "POST",
            collection_path,
            key=keys["read"],
            body={"paper_ids": ["W123"]},
        ),
        await _request(app, "GET", run_path, key=keys["bob"]),
        await _request(app, "GET", f"/v1/research/{uuid4()}", key=keys["bob"]),
        await _request(
            app,
            "POST",
            "/v1/research",
            key=keys["alice"],
            body=_body("q" * 2001),
        ),
        await _request(
            app,
            "POST",
            "/v1/research",
            key=keys["alice"],
            content=b"x" * (70 * 1024),
        ),
        await _hostile_paper_id(app, keys["read"], "/v1/papers/..%2F..%2Fetc%2Fpasswd"),
        await _hostile_paper_id(app, keys["read"], "/v1/papers/W1'%20OR%201=1"),
    ]
    rate_store = InMemoryApiKeyStore()
    _, rate_key = await rate_store.create("rate-client", (Scope.RESEARCH,))
    rate_settings = RateLimitSettings(
        {**DEFAULT_LIMITS, RouteClass.RESEARCH_CREATE: Limit(20, 3600)},
        max_active_runs_per_principal=100,
    )
    rate_app = _app(key_store=rate_store, rate_limits=rate_settings)
    for _ in range(21):
        rate_error = await _request(
            rate_app, "POST", "/v1/research", key=rate_key, body=_body()
        )
    errors.append(rate_error)

    for response in errors:
        body = response.text
        assert "Traceback" not in body
        assert 'File "' not in body
        for submitted_key in (
            _KEY,
            revoked_key,
            keys["alice"],
            keys["alice"].upper(),
            keys["bob"],
            keys["read"],
            rate_key,
        ):
            assert submitted_key not in body
