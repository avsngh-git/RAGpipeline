"""Tests for bounded OpenAlex discovery requests and response contracts."""

import asyncio

import httpx
import pytest

from research_platform.ingestion.config import (
    DiscoveryConfig,
    DiscoveryLimits,
    YearRange,
)
from research_platform.ingestion.openalex import (
    DiscoveryPage,
    OpenAlexClient,
    OpenAlexNotFound,
    OpenAlexRequestError,
    OpenAlexResponseError,
    OpenAlexWork,
)


def _config(
    *,
    queries: tuple[str, ...] = ("hybrid retrieval",),
    limits: DiscoveryLimits | None = None,
) -> DiscoveryConfig:
    return DiscoveryConfig(
        queries=queries,
        year_range=YearRange(start_year=2020, end_year=2026),
        limits=limits or DiscoveryLimits(),
    )


def _work(
    openalex_id: str = "W123",
    *,
    score: float = 12.5,
) -> dict[str, object]:
    return {
        "id": f"https://openalex.org/{openalex_id}",
        "title": "A paper on hybrid retrieval",
        "publication_year": 2024,
        "language": "en",
        "type": "article",
        "doi": "https://doi.org/10.1234/EXAMPLE",
        "cited_by_count": 7,
        "abstract_inverted_index": {"Hybrid": [0], "retrieval": [1]},
        "relevance_score": score,
    }


def _page(
    results: list[dict[str, object]], next_cursor: str | None, count: int = 1
) -> dict[str, object]:
    return {
        "meta": {
            "count": count,
            "next_cursor": next_cursor,
            "cost_usd": 0.001,
        },
        "results": results,
    }


async def _no_sleep(_delay: float) -> None:
    return None


def test_search_page_uses_bounded_query_and_hides_key_in_url() -> None:
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_page([_work()], None))

    async def exercise() -> DiscoveryPage:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                _config(), "test-secret", http, sleep=_no_sleep, clock=lambda: 0.0
            )
            page = await client.search_page("hybrid retrieval", "cursor-token")
            return DiscoveryPage(0, "hybrid retrieval", 1, "cursor-token", page)

    result = asyncio.run(exercise())
    request = captured[0]

    assert request.url.host == "api.openalex.org"
    assert request.url.path == "/works"
    assert request.url.params["search"] == "hybrid retrieval"
    assert request.url.params["filter"] == ("publication_year:2020-2026,language:en")
    assert request.url.params["per_page"] == "100"
    assert request.url.params["cursor"] == "cursor-token"
    assert request.url.params["corpus"] == "all"
    assert "test-secret" not in str(request.url)
    assert request.headers["Authorization"] == "Bearer test-secret"
    assert result.page.results[0].openalex_id == "W123"
    assert result.page.results[0].doi == "10.1234/example"
    assert result.page.results[0].has_abstract is True
    assert result.page.api_cost_usd == 0.001


def test_pages_follow_cursor_and_keep_query_origin_and_page_numbers() -> None:
    cursors: list[str] = []
    payloads = [
        _page([_work("W123")], "next-cursor", count=2),
        _page([_work("W456")], None, count=2),
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        cursors.append(request.url.params["cursor"])
        return httpx.Response(200, json=payloads[len(cursors) - 1])

    async def exercise() -> list[DiscoveryPage]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                _config(), "test-secret", http, sleep=_no_sleep, clock=lambda: 0.0
            )
            return [page async for page in client.pages()]

    pages = asyncio.run(exercise())

    assert cursors == ["*", "next-cursor"]
    assert [page.page_number for page in pages] == [1, 2]
    assert [page.query_index for page in pages] == [0, 0]
    assert [work.openalex_id for page in pages for work in page.page.results] == [
        "W123",
        "W456",
    ]


def test_pages_resume_from_saved_query_cursor_and_page_number() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_page([_work()], None))

    async def exercise() -> list[DiscoveryPage]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                _config(queries=("first query", "second query")),
                "test-secret",
                http,
                sleep=_no_sleep,
                clock=lambda: 0.0,
            )
            return [
                page
                async for page in client.pages(
                    start_query_index=1,
                    start_cursor="saved-cursor",
                    start_page_number=2,
                )
            ]

    pages = asyncio.run(exercise())

    assert len(requests) == 1
    assert requests[0].url.params["search"] == "second query"
    assert requests[0].url.params["cursor"] == "saved-cursor"
    assert pages[0].page_number == 3


def test_retry_honors_retry_after_and_reserves_each_attempt() -> None:
    statuses = [429, 200]
    sleeps: list[float] = []
    reservations: list[bool] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        status = statuses.pop(0)
        headers = {"Retry-After": "0"} if status == 429 else {}
        return httpx.Response(
            status,
            headers=headers,
            json=_page([_work()], None),
        )

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    async def reserve() -> None:
        reservations.append(True)

    async def exercise() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                _config(),
                "test-secret",
                http,
                reserve_request=reserve,
                sleep=sleep,
                clock=lambda: 0.0,
            )
            await client.search_page("hybrid retrieval")
            return client.requests_used

    assert asyncio.run(exercise()) == 2
    assert reservations == [True, True]
    assert sleeps == [0.0, 1.0]


def test_total_request_limit_counts_retries() -> None:
    calls: list[bool] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        calls.append(True)
        return httpx.Response(503)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                _config(limits=DiscoveryLimits(max_total_requests=1)),
                "test-secret",
                http,
                sleep=_no_sleep,
                clock=lambda: 0.0,
            )
            with pytest.raises(OpenAlexRequestError, match="total request limit"):
                await client.search_page("hybrid retrieval")

    asyncio.run(exercise())
    assert calls == [True]


def test_non_retryable_http_error_fails_without_retry() -> None:
    calls: list[bool] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        calls.append(True)
        return httpx.Response(400)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                _config(), "test-secret", http, sleep=_no_sleep, clock=lambda: 0.0
            )
            with pytest.raises(OpenAlexRequestError, match="HTTP 400"):
                await client.search_page("hybrid retrieval")

    asyncio.run(exercise())
    assert calls == [True]


def test_malformed_work_response_fails_clearly() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_page([{"title": "No ID"}], None))

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                _config(), "test-secret", http, sleep=_no_sleep, clock=lambda: 0.0
            )
            with pytest.raises(OpenAlexResponseError, match="OpenAlex id"):
                await client.search_page("hybrid retrieval")

    asyncio.run(exercise())


def test_live_discovery_requires_api_key() -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_page([], None))

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with pytest.raises(ValueError, match="API key is required"):
        OpenAlexClient(_config(), "  ", http)
    asyncio.run(http.aclose())


def test_openalex_work_rejects_invalid_numeric_types() -> None:
    payload = _work()
    payload["publication_year"] = True
    with pytest.raises(OpenAlexResponseError, match="publication_year"):
        OpenAlexWork.from_payload(payload)


def test_explicit_older_exception_uses_direct_work_lookup() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_work("W17"))

    async def exercise() -> DiscoveryPage:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                _config(), "test-secret", http, sleep=_no_sleep, clock=lambda: 0.0
            )
            return await client.get_older_exception("W17", query_index=4)

    page = asyncio.run(exercise())

    assert requests[0].url.path == "/works/W17"
    assert page.query_index == 4
    assert page.query == "older_exception:W17"
    assert page.page.results[0].openalex_id == "W17"


def test_resume_obeys_absolute_per_query_page_limit() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_page([_work()], "more-results"))

    async def exercise() -> list[DiscoveryPage]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            config = _config(
                limits=DiscoveryLimits(max_pages_per_query=3, max_total_requests=5)
            )
            client = OpenAlexClient(
                config, "test-secret", http, sleep=_no_sleep, clock=lambda: 0.0
            )
            return [
                page
                async for page in client.pages_for_query(
                    0, start_cursor="resume-cursor", start_page_number=2
                )
            ]

    pages = asyncio.run(exercise())

    assert len(requests) == 1
    assert requests[0].url.params["cursor"] == "resume-cursor"
    assert [page.page_number for page in pages] == [3]


def test_direct_work_lookup_supports_citation_metadata_enrichment() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_work("W999"))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                _config(), "test-secret", http, sleep=_no_sleep, clock=lambda: 0.0
            )
            work = await client.get_work_metadata("https://openalex.org/W999")
            return client, work

    client, work = asyncio.run(exercise())

    assert requests[0].url.path == "/works/W999"
    assert "test-secret" not in str(requests[0].url)
    assert client.configuration_id == _config().config_id
    assert client.request_limit == 50
    assert work.openalex_id == "W999"
    assert work.metadata["title"] == "A paper on hybrid retrieval"


def test_direct_work_lookup_marks_unknown_citation_ids_not_found() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                _config(), "test-secret", http, sleep=_no_sleep, clock=lambda: 0.0
            )
            with pytest.raises(OpenAlexNotFound):
                await client.get_work_metadata("W999")

    asyncio.run(exercise())
