"""API contract tests."""

import asyncio

import httpx
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.api.errors import AppError
from research_platform.observability.request_context import get_request_id
from research_platform.services.readiness import ReadinessReport


class StubReadinessChecker:
    def __init__(self, report: ReadinessReport) -> None:
        self._report = report

    async def check(self) -> ReadinessReport:
        return self._report


async def _request(
    app: FastAPI,
    path: str,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


def test_health_returns_liveness_response() -> None:
    response = asyncio.run(_request(create_app(), "/health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_generates_request_id() -> None:
    response = asyncio.run(_request(create_app(), "/health"))

    assert response.headers["x-request-id"]


def test_request_id_is_preserved_and_available_to_handlers() -> None:
    app = create_app()

    @app.get("/request-id")
    async def request_id() -> dict[str, str | None]:
        return {"request_id": get_request_id()}

    response = asyncio.run(
        _request(app, "/request-id", headers={"X-Request-ID": "request-123"})
    )

    assert response.headers["x-request-id"] == "request-123"
    assert response.json() == {"request_id": "request-123"}


def test_expected_error_has_safe_structured_response() -> None:
    app = create_app()

    @app.get("/expected-error")
    async def expected_error() -> None:
        raise AppError("invalid_request", "The request is invalid.", status_code=422)

    response = asyncio.run(
        _request(app, "/expected-error", headers={"X-Request-ID": "request-456"})
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "The request is invalid.",
            "request_id": "request-456",
        }
    }


def test_unexpected_error_does_not_leak_internal_details() -> None:
    app = create_app()

    @app.get("/unexpected-error")
    async def unexpected_error() -> None:
        raise RuntimeError("database password should not be returned")

    response = asyncio.run(_request(app, "/unexpected-error"))

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "database password" not in response.text


def test_ready_returns_ok_when_dependencies_are_available() -> None:
    checker = StubReadinessChecker(
        ReadinessReport(dependencies={"postgres": True, "qdrant": True})
    )

    response = asyncio.run(_request(create_app(dependency_checker=checker), "/ready"))

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"postgres": "ok", "qdrant": "ok"},
    }


def test_ready_returns_service_unavailable_when_dependency_is_down() -> None:
    checker = StubReadinessChecker(
        ReadinessReport(dependencies={"postgres": False, "qdrant": True})
    )

    response = asyncio.run(_request(create_app(dependency_checker=checker), "/ready"))

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {"postgres": "unavailable", "qdrant": "ok"},
    }
