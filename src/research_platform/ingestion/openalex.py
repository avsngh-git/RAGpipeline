"""Bounded OpenAlex works search and response normalization."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import cast

import httpx

from research_platform.ingestion.config import DiscoveryConfig

OPENALEX_API_BASE = "https://api.openalex.org"
_OPENALEX_ID_PATTERN = re.compile(r"^W[0-9]+$")
_SELECT_FIELDS = ",".join(
    (
        "id",
        "title",
        "doi",
        "publication_year",
        "language",
        "type",
        "cited_by_count",
        "primary_location",
        "locations",
        "authorships",
        "abstract_inverted_index",
        "referenced_works",
        "has_content",
        "content_urls",
        "best_oa_location",
    )
)


class OpenAlexRequestError(RuntimeError):
    """A bounded OpenAlex request failed or exceeded its configured budget."""


class OpenAlexNotFound(OpenAlexRequestError):
    """OpenAlex has no work record for a requested identifier."""


class OpenAlexResponseError(ValueError):
    """OpenAlex returned malformed data that cannot be safely normalized."""


@dataclass(frozen=True)
class OpenAlexWork:
    openalex_id: str
    title: str | None
    publication_year: int | None
    language: str | None
    work_type: str | None
    doi: str | None
    cited_by_count: int | None
    relevance_score: float | None
    has_abstract: bool
    metadata: Mapping[str, object]

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> OpenAlexWork:
        raw_id = payload.get("id")
        if not isinstance(raw_id, str):
            raise OpenAlexResponseError("work is missing a string OpenAlex id")
        openalex_id = raw_id.removeprefix("https://openalex.org/")
        if not _OPENALEX_ID_PATTERN.fullmatch(openalex_id):
            raise OpenAlexResponseError("work has an invalid OpenAlex id")

        title = payload.get("title")
        if title is not None and not isinstance(title, str):
            raise OpenAlexResponseError("work title must be a string or null")
        if isinstance(title, str) and not title.strip():
            title = None

        publication_year = payload.get("publication_year")
        if publication_year is not None and (
            isinstance(publication_year, bool) or not isinstance(publication_year, int)
        ):
            raise OpenAlexResponseError(
                "work publication_year must be an integer or null"
            )

        language = payload.get("language")
        if language is not None and not isinstance(language, str):
            raise OpenAlexResponseError("work language must be a string or null")

        work_type = payload.get("type")
        if work_type is not None and not isinstance(work_type, str):
            raise OpenAlexResponseError("work type must be a string or null")

        doi = payload.get("doi")
        if doi is not None and not isinstance(doi, str):
            raise OpenAlexResponseError("work DOI must be a string or null")
        if doi is not None:
            doi = doi.removeprefix("https://doi.org/").lower()

        cited_by_count = payload.get("cited_by_count")
        if cited_by_count is not None and (
            isinstance(cited_by_count, bool)
            or not isinstance(cited_by_count, int)
            or cited_by_count < 0
        ):
            raise OpenAlexResponseError(
                "work cited_by_count must be a non-negative integer"
            )

        score_value = payload.get("relevance_score")
        if score_value is not None and (
            isinstance(score_value, bool) or not isinstance(score_value, (int, float))
        ):
            raise OpenAlexResponseError("work relevance_score must be a number or null")

        abstract_index = payload.get("abstract_inverted_index")
        if abstract_index is not None and not isinstance(abstract_index, Mapping):
            raise OpenAlexResponseError("work abstract index must be an object or null")

        return cls(
            openalex_id=openalex_id,
            title=title,
            publication_year=publication_year,
            language=language,
            work_type=work_type,
            doi=doi,
            cited_by_count=cited_by_count,
            relevance_score=(float(score_value) if score_value is not None else None),
            has_abstract=bool(abstract_index),
            metadata=cast(Mapping[str, object], dict(payload)),
        )


@dataclass(frozen=True)
class OpenAlexPage:
    next_cursor: str | None
    results: tuple[OpenAlexWork, ...]
    result_count: int | None
    api_cost_usd: float
    source_metadata: Mapping[str, object]


@dataclass(frozen=True)
class DiscoveryPage:
    query_index: int
    query: str
    page_number: int
    cursor_used: str
    page: OpenAlexPage


RequestReservation = Callable[[], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class OpenAlexClient:
    """Issue rate-limited, cursor-paged Works API requests with bounded retries."""

    def __init__(
        self,
        config: DiscoveryConfig,
        api_key: str,
        http_client: httpx.AsyncClient,
        *,
        reserve_request: RequestReservation | None = None,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        if not api_key.strip():
            raise ValueError("an OpenAlex API key is required for live discovery")
        self._config = config
        self._api_key = api_key
        self._http_client = http_client
        self._reserve_request = reserve_request
        self._sleep = sleep
        self._clock = clock
        self._requests_used = 0
        self._next_request_at = 0.0

    @property
    def requests_used(self) -> int:
        return self._requests_used

    @property
    def request_limit(self) -> int:
        return self._config.limits.max_total_requests

    @property
    def configuration_id(self) -> str:
        return self._config.config_id

    async def get_work_metadata(self, openalex_id: str) -> OpenAlexWork:
        """Fetch one work by ID for bounded unresolved-citation enrichment."""
        normalized_id = openalex_id.removeprefix("https://openalex.org/")
        if not _OPENALEX_ID_PATTERN.fullmatch(normalized_id):
            raise ValueError("OpenAlex work IDs must look like W123")
        payload, _response = await self._get_json(
            f"/works/{normalized_id}", {"select": _SELECT_FIELDS}
        )
        work = OpenAlexWork.from_payload(payload)
        if work.openalex_id != normalized_id:
            raise OpenAlexResponseError("OpenAlex returned a different work ID")
        return work

    async def search_page(self, query: str, cursor: str = "*") -> OpenAlexPage:
        """Fetch one Works page for a configured query and cursor."""
        year_range = self._config.year_range
        params = {
            "search": query,
            "filter": (
                f"publication_year:{year_range.start_year}-{year_range.end_year},"
                f"language:{self._config.language}"
            ),
            "per_page": str(self._config.limits.per_page),
            "cursor": cursor,
            "select": _SELECT_FIELDS,
            "corpus": "all",
        }
        payload, response = await self._get_json("/works", params)
        return self._parse_page(payload, response)

    async def get_older_exception(
        self, openalex_id: str, query_index: int
    ) -> DiscoveryPage:
        """Fetch one explicitly configured foundational work by OpenAlex ID."""
        normalized_id = openalex_id.removeprefix("https://openalex.org/")
        if not _OPENALEX_ID_PATTERN.fullmatch(normalized_id):
            raise ValueError("older-paper exceptions must be OpenAlex work IDs")
        payload, response = await self._get_json(
            f"/works/{normalized_id}",
            {"select": _SELECT_FIELDS.replace(",relevance_score", "")},
        )
        work = OpenAlexWork.from_payload(payload)
        meta: Mapping[str, object] = {
            "lookup": "explicit_older_paper_exception",
            "openalex_id": normalized_id,
        }
        cost_value = response.headers.get("X-RateLimit-Credits-Used", "0")
        try:
            api_cost = float(cost_value)
        except ValueError:
            api_cost = 0.0
        return DiscoveryPage(
            query_index=query_index,
            query=f"older_exception:{normalized_id}",
            page_number=1,
            cursor_used=f"id:{normalized_id}",
            page=OpenAlexPage(
                next_cursor=None,
                results=(work,),
                result_count=1,
                api_cost_usd=api_cost,
                source_metadata=meta,
            ),
        )

    async def pages_for_query(
        self,
        query_index: int,
        *,
        start_cursor: str = "*",
        start_page_number: int = 0,
    ) -> AsyncIterator[DiscoveryPage]:
        """Yield bounded pages for one query from a persisted cursor position."""
        if not 0 <= query_index < len(self._config.queries):
            raise ValueError("query_index is outside the configured query list")
        query = self._config.queries[query_index]
        cursor = start_cursor
        page_number = start_page_number + 1
        remaining_pages = self._config.limits.max_pages_per_query - start_page_number
        for _ in range(max(0, remaining_pages)):
            result = await self.search_page(query, cursor)
            yield DiscoveryPage(
                query_index=query_index,
                query=query,
                page_number=page_number,
                cursor_used=cursor,
                page=result,
            )
            if result.next_cursor is None:
                break
            cursor = result.next_cursor
            page_number += 1

    async def pages(
        self,
        *,
        start_query_index: int = 0,
        start_cursor: str = "*",
        start_page_number: int = 0,
    ) -> AsyncIterator[DiscoveryPage]:
        """Yield all configured query pages from a persisted cursor position."""
        for query_index in range(start_query_index, len(self._config.queries)):
            cursor = start_cursor if query_index == start_query_index else "*"
            page_number = start_page_number if query_index == start_query_index else 0
            async for page in self.pages_for_query(
                query_index,
                start_cursor=cursor,
                start_page_number=page_number,
            ):
                yield page

    async def _get_json(
        self, path: str, params: Mapping[str, str]
    ) -> tuple[Mapping[str, object], httpx.Response]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for retry_number in range(self._config.limits.max_retries + 1):
            await self._wait_for_rate_limit()
            if self._requests_used >= self._config.limits.max_total_requests:
                raise OpenAlexRequestError("OpenAlex total request limit reached")
            if self._reserve_request is not None:
                await self._reserve_request()
            self._requests_used += 1

            try:
                response = await self._http_client.get(
                    f"{OPENALEX_API_BASE}{path}",
                    params=params,
                    headers=headers,
                    timeout=self._config.limits.timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.TransportError) as error:
                if retry_number >= self._config.limits.max_retries:
                    raise OpenAlexRequestError(
                        f"OpenAlex request failed after {self._requests_used} attempts"
                    ) from error
                await self._sleep(self._backoff_seconds(retry_number))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if retry_number >= self._config.limits.max_retries:
                    raise OpenAlexRequestError(
                        f"OpenAlex returned HTTP {response.status_code} after retries"
                    )
                await self._sleep(self._retry_delay(response, retry_number))
                continue
            if response.status_code == 404:
                raise OpenAlexNotFound(
                    "OpenAlex has no work record for this identifier"
                )
            if 300 <= response.status_code < 400:
                raise OpenAlexRequestError("OpenAlex returned an unexpected redirect")
            if response.is_error:
                raise OpenAlexRequestError(
                    f"OpenAlex returned HTTP {response.status_code}"
                )

            try:
                payload = response.json()
            except ValueError as error:
                raise OpenAlexResponseError(
                    "OpenAlex response was not valid JSON"
                ) from error
            if not isinstance(payload, Mapping):
                raise OpenAlexResponseError("OpenAlex response must be a JSON object")
            return cast(Mapping[str, object], payload), response

        raise OpenAlexRequestError("OpenAlex request exhausted its retry limit")

    async def _wait_for_rate_limit(self) -> None:
        delay = self._next_request_at - self._clock()
        if delay > 0:
            await self._sleep(delay)
        self._next_request_at = self._clock() + max(
            1.0,
            self._config.limits.minimum_request_interval_seconds,
        )

    def _retry_delay(self, response: httpx.Response, retry_number: int) -> float:
        header_value = response.headers.get("Retry-After")
        if header_value is not None:
            try:
                return max(0.0, min(float(header_value), 60.0))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(header_value).timestamp()
                    return max(0.0, min(retry_at - time.time(), 60.0))
                except (TypeError, ValueError, OverflowError):
                    pass
        return self._backoff_seconds(retry_number)

    @staticmethod
    def _backoff_seconds(retry_number: int) -> float:
        return min(float(2**retry_number), 30.0)

    @staticmethod
    def _parse_page(
        payload: Mapping[str, object], response: httpx.Response
    ) -> OpenAlexPage:
        meta = payload.get("meta")
        results_value = payload.get("results")
        if not isinstance(meta, Mapping) or not isinstance(results_value, list):
            raise OpenAlexResponseError("OpenAlex response is missing meta or results")

        next_cursor = meta.get("next_cursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise OpenAlexResponseError("OpenAlex next_cursor must be a string or null")
        count_value = meta.get("count")
        if count_value is not None and (
            isinstance(count_value, bool) or not isinstance(count_value, int)
        ):
            raise OpenAlexResponseError("OpenAlex result count must be an integer")
        cost_value = meta.get("cost_usd")
        if cost_value is None:
            cost_value = response.headers.get("X-RateLimit-Credits-Used", "0")
        if isinstance(cost_value, bool) or not isinstance(
            cost_value, (int, float, str)
        ):
            cost_value = 0.0
        try:
            api_cost = float(cost_value)
        except ValueError:
            api_cost = 0.0

        works: list[OpenAlexWork] = []
        for result in results_value:
            if not isinstance(result, Mapping):
                raise OpenAlexResponseError("OpenAlex results must contain objects")
            works.append(OpenAlexWork.from_payload(result))
        return OpenAlexPage(
            next_cursor=next_cursor,
            results=tuple(works),
            result_count=count_value,
            api_cost_usd=api_cost,
            source_metadata=cast(Mapping[str, object], dict(meta)),
        )
