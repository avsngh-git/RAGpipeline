"""The API's shared OpenAlex client must outlast the per-run request limit."""

from __future__ import annotations

import asyncio

import httpx

from research_platform.api.app import api_discovery_config
from research_platform.config import DiscoverySettings
from research_platform.ingestion.openalex import OpenAlexClient


async def _no_sleep(_delay: float) -> None:
    return None


def test_client_limit_is_not_the_per_run_limit() -> None:
    settings = DiscoverySettings()

    limits = api_discovery_config(settings).limits

    assert limits.max_total_requests > 100 * settings.max_search_requests_per_run
    assert limits.per_page == settings.results_per_request


def test_shared_client_serves_more_requests_than_one_run_may_make() -> None:
    settings = DiscoverySettings()
    calls = settings.max_search_requests_per_run + 5

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    async def exercise() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                api_discovery_config(settings),
                "test-secret",
                http,
                sleep=_no_sleep,
                clock=lambda: 0.0,
            )
            for _ in range(calls):
                await client.search_page("reranking")
            return client.requests_used

    assert asyncio.run(exercise()) == calls
