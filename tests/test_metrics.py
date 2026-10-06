"""Prometheus metrics and HTTP request instrumentation tests."""

from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.observability.metrics import REGISTRY
from research_platform.services.readiness import ReadinessReport


class StubReadinessChecker:
    def __init__(self) -> None:
        self._report = ReadinessReport(dependencies={"postgres": True, "qdrant": True})

    async def check(self) -> ReadinessReport:
        return self._report


async def _request(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def _app() -> FastAPI:
    return create_app(dependency_checker=StubReadinessChecker())


def test_metrics_endpoint_serves_prometheus_text() -> None:
    response = asyncio.run(_request(_app(), "/metrics"))

    assert response.status_code == 200
    assert "research_http_requests_total" in response.text
    assert "text/plain" in response.headers["content-type"]


def test_health_request_is_counted_by_template() -> None:
    labels = {"method": "GET", "route": "/health", "status": "200"}
    before = REGISTRY.get_sample_value("research_http_requests_total", labels) or 0

    response = asyncio.run(_request(_app(), "/health"))

    after = REGISTRY.get_sample_value("research_http_requests_total", labels) or 0
    assert response.status_code == 200
    assert after == before + 1


def test_path_parameters_use_template() -> None:
    response = asyncio.run(_request(_app(), "/v1/papers/W123"))

    sample = REGISTRY.get_sample_value(
        "research_http_requests_total",
        {
            "method": "GET",
            "route": "/v1/papers/{paper_id}",
            "status": str(response.status_code),
        },
    )
    assert sample is not None and sample >= 1


def test_unknown_path_is_unmatched() -> None:
    response = asyncio.run(_request(_app(), "/not-a-route"))

    sample = REGISTRY.get_sample_value(
        "research_http_requests_total",
        {"method": "GET", "route": "unmatched", "status": str(response.status_code)},
    )
    assert sample is not None and sample >= 1


def test_metrics_requests_are_not_counted() -> None:
    before = sum(
        sample.value
        for family in REGISTRY.collect()
        for sample in family.samples
        if sample.name == "research_http_requests_total"
    )

    asyncio.run(_request(_app(), "/metrics"))

    after = sum(
        sample.value
        for family in REGISTRY.collect()
        for sample in family.samples
        if sample.name == "research_http_requests_total"
    )
    assert after == before


def test_all_metric_names_have_prefix() -> None:
    assert REGISTRY.collect()
    assert all(family.name.startswith("research_") for family in REGISTRY.collect())
