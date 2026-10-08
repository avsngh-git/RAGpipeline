"""Rate limit and request size protection tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from research_platform.api import create_app
from research_platform.api.body_limit import BodySizeLimitMiddleware
from research_platform.api.errors import handle_http_error
from research_platform.api.rate_limits import (
    DEFAULT_LIMITS,
    Limit,
    RateLimitSettings,
    RouteClass,
    TokenBucketLimiter,
)
from research_platform.config import Settings
from research_platform.observability.metrics import RATE_LIMITED


def test_bucket_allows_capacity_then_limits() -> None:
    limiter = TokenBucketLimiter(RateLimitSettings(DEFAULT_LIMITS))
    for _ in range(DEFAULT_LIMITS[RouteClass.SEARCH].capacity):
        assert limiter.check("key", RouteClass.SEARCH) is None
    assert limiter.check("key", RouteClass.SEARCH) is not None


def test_bucket_refills_over_time() -> None:
    now = [0.0]
    limiter = TokenBucketLimiter(
        RateLimitSettings({RouteClass.SEARCH: Limit(1, 10)}), clock=lambda: now[0]
    )
    assert limiter.check("key", RouteClass.SEARCH) is None
    assert limiter.check("key", RouteClass.SEARCH) == 10
    now[0] = 10
    assert limiter.check("key", RouteClass.SEARCH) is None


def test_buckets_are_per_principal_and_class() -> None:
    limits = {route: Limit(1, 60) for route in RouteClass}
    limiter = TokenBucketLimiter(RateLimitSettings(limits))
    assert limiter.check("one", RouteClass.SEARCH) is None
    assert limiter.check("one", RouteClass.PAPER_READ) is None
    assert limiter.check("two", RouteClass.SEARCH) is None


def test_bucket_eviction_bound() -> None:
    limiter = TokenBucketLimiter(
        RateLimitSettings({RouteClass.SEARCH: Limit(1, 60)}), max_buckets=1
    )
    assert limiter.check("one", RouteClass.SEARCH) is None
    assert limiter.check("two", RouteClass.SEARCH) is None
    assert len(limiter._buckets) == 1
    assert ("two", RouteClass.SEARCH) in limiter._buckets


def test_from_env_parses_and_rejects() -> None:
    parsed = RateLimitSettings.from_env(
        {
            "RESEARCH_PLATFORM_RATE_LIMIT_SEARCH": "3/15",
            "RESEARCH_PLATFORM_MAX_BODY_BYTES": "42",
        }
    )
    assert parsed.limits[RouteClass.SEARCH] == Limit(3, 15)
    assert parsed.max_body_bytes == 42
    with pytest.raises(ValueError):
        RateLimitSettings.from_env({"RESEARCH_PLATFORM_RATE_LIMIT_SEARCH": "0/15"})
    with pytest.raises(ValueError):
        RateLimitSettings.from_env({"RESEARCH_PLATFORM_MAX_ACTIVE_RUNS_PER_KEY": "bad"})


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://test:test@localhost:5432/research_test",
        qdrant_url="http://localhost:26333",
    )


async def _call(
    app: FastAPI, method: str, path: str, **kwargs: object
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_search_over_limit_is_429_with_retry_after() -> None:
    app = create_app(
        settings=_settings(),
        rate_limit_settings=RateLimitSettings(
            {**DEFAULT_LIMITS, RouteClass.SEARCH: Limit(2, 60)}
        ),
    )
    app.state.auth_settings = type("DisabledAuth", (), {"mode": "disabled"})()
    app.state.rate_limiter = TokenBucketLimiter(app.state.rate_limit_settings)
    for _ in range(3):
        response = asyncio.run(_call(app, "POST", "/v1/search", json={}))
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["retry-after"]) >= 1


def test_active_run_cap() -> None:
    from uuid import UUID

    from research_platform.api.research_routes import ResearchAPIServices
    from research_platform.runs.memory import InMemoryRunStore
    from research_platform.runs.runner import ServingIdentity

    class Executor:
        async def submit(self, _run_id: UUID, *, request_id: str | None = None) -> None:
            return None

    store = InMemoryRunStore()
    app = create_app(
        settings=_settings(),
        research_services=ResearchAPIServices(
            store=store,
            executor=Executor(),  # type: ignore[arg-type]
            serving=ServingIdentity(
                UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c"), "profile"
            ),
        ),
    )
    body = {"question": "synthetic", "mode": "quick"}
    for _ in range(2):
        response = asyncio.run(_call(app, "POST", "/v1/research", json=body))
        assert response.status_code == 202
    response = asyncio.run(_call(app, "POST", "/v1/research", json=body))
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_active_runs"


def _body_app(max_bytes: int = 65536) -> FastAPI:
    app = FastAPI()

    @app.post("/body")
    async def body(request: Request) -> dict[str, bool]:
        await request.body()
        return {"ok": True}

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)
    return app


def test_body_over_limit_by_header_is_413() -> None:
    response = asyncio.run(_call(_body_app(), "POST", "/body", content=b"x" * 65537))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_body_over_limit_streamed_is_413() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"x" * 35000
        yield b"x" * 35000

    response = asyncio.run(_call(_body_app(), "POST", "/body", content=chunks()))
    assert response.status_code == 413


class _Payload(BaseModel):
    text: str


def _model_body_app(max_bytes: int = 65536) -> FastAPI:
    """A route whose body FastAPI parses into a model, as the real routes do."""
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, handle_http_error)

    @app.post("/model")
    async def model(payload: _Payload) -> dict[str, int]:
        return {"length": len(payload.text)}

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)
    return app


def test_streamed_body_over_limit_on_a_model_route_is_413() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b'{"text": "' + b"x" * 40000
        yield b"x" * 40000 + b'"}'

    response = asyncio.run(_call(_model_body_app(), "POST", "/model", content=chunks()))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_unknown_route_uses_the_error_envelope() -> None:
    response = asyncio.run(_call(create_app(settings=_settings()), "GET", "/nope"))

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert "request_id" in error


def test_wrong_method_uses_the_error_envelope_and_keeps_allow() -> None:
    response = asyncio.run(_call(create_app(settings=_settings()), "DELETE", "/health"))

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert response.headers["allow"] == "GET"


def test_small_body_passes() -> None:
    response = asyncio.run(_call(_body_app(), "POST", "/body", content=b"{}"))
    assert response.status_code == 200


def test_rate_limited_metric_increments() -> None:
    sample = RATE_LIMITED.labels(RouteClass.SEARCH.value)
    before = sample._value.get()
    app = create_app(
        settings=_settings(),
        rate_limit_settings=RateLimitSettings(
            {**DEFAULT_LIMITS, RouteClass.SEARCH: Limit(1, 60)}
        ),
    )
    app.state.auth_settings = type("DisabledAuth", (), {"mode": "disabled"})()
    app.state.rate_limiter = TokenBucketLimiter(app.state.rate_limit_settings)
    for _ in range(2):
        asyncio.run(_call(app, "POST", "/v1/search", json={}))
    assert sample._value.get() == before + 1
