"""Citation enrichment follows OpenAlex merges and keeps the cited ID."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, cast

import httpx

from research_platform.ingestion.citations import (
    UnresolvedCitationTarget,
    enrich_unresolved_citations,
)
from research_platform.ingestion.config import (
    DiscoveryConfig,
    DiscoveryLimits,
    YearRange,
)
from research_platform.ingestion.openalex import OpenAlexClient


class _Repository:
    def __init__(self, targets: tuple[UnresolvedCitationTarget, ...]) -> None:
        self.targets = targets
        self.results: list[tuple[str, str, Mapping[str, object]]] = []

    async def pending_targets(self, limit: int) -> tuple[UnresolvedCitationTarget, ...]:
        return self.targets[:limit]

    async def record_result(
        self,
        target: UnresolvedCitationTarget,
        status: str,
        metadata: Mapping[str, object],
        configuration_id: str,
        code_revision: str,
    ) -> bool:
        del configuration_id, code_revision
        self.results.append((target.identifier, status, metadata))
        return True


def _work(openalex_id: str) -> dict[str, object]:
    return {
        "id": f"https://openalex.org/{openalex_id}",
        "title": "Merged paper",
        "publication_year": 2024,
        "abstract_inverted_index": None,
    }


async def _no_sleep(_delay: float) -> None:
    return None


def test_merged_citation_is_recorded_with_its_cited_id() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/works/W111":
            return httpx.Response(
                301, headers={"location": "https://api.openalex.org/works/W222"}
            )
        return httpx.Response(200, json=_work("W222"))

    repository = _Repository(
        (UnresolvedCitationTarget(namespace="openalex", identifier="W111"),)
    )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = OpenAlexClient(
                DiscoveryConfig(
                    queries=("citations",),
                    year_range=YearRange(2020, 2026),
                    limits=DiscoveryLimits(),
                ),
                "test-secret",
                http,
                sleep=_no_sleep,
                clock=lambda: 0.0,
            )
            outcome = await enrich_unresolved_citations(
                cast(Any, repository),
                client,
                limit=5,
                code_revision="test",
            )
            assert outcome.metadata_found == 1

    asyncio.run(exercise())

    ((identifier, status, metadata),) = repository.results
    assert (identifier, status) == ("W111", "found")
    assert metadata["merged_from"] == "W111"
    assert metadata["id"] == "https://openalex.org/W222"
