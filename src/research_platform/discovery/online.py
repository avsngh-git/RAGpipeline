"""Budgeted online discovery of recent, English OpenAlex works.

Field filters use OpenAlex's ``primary_topic.field.id`` path. OpenAlex combines
comma-separated filters with AND and pipe-separated values with OR; see
https://help.openalex.org/data/fields/ and
https://help.openalex.org/api/filtering/.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.config import DiscoverySettings
from research_platform.ingestion.catalog import CatalogRepository
from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationPoint,
    GenerationQdrantCollection,
    paper_point_id,
)
from research_platform.ingestion.indexing import VectorEmbedder
from research_platform.ingestion.openalex import (
    OpenAlexClient,
    OpenAlexWork,
    abstract_from_openalex_metadata,
)
from research_platform.ingestion.paper_index import (
    CatalogStatus,
    PaperIndexInput,
    SparsePaperEncoder,
    paper_lexical_text,
    paper_payload,
)

SpendKind = Literal["search_request", "content_download"]
BudgetReason = Literal["run_search_limit", "daily_spend_cap"]


class DiscoveryBudgetExceeded(RuntimeError):
    """A search or download reservation could not fit within its budget."""

    def __init__(self, reason: BudgetReason) -> None:
        self.reason = reason
        if reason == "run_search_limit":
            message = "online discovery reached its per-run request limit"
        elif reason == "daily_spend_cap":
            message = "online discovery reached its UTC daily spend cap"
        else:
            raise ValueError("unsupported discovery budget reason")
        super().__init__(message)


@dataclass(frozen=True)
class DiscoveredPaper:
    paper_id: str
    openalex_id: str
    title: str | None
    publication_year: int | None
    abstract: str | None
    similarity: float
    catalog_status: CatalogStatus


def openalex_search_query(query: str) -> str:
    """Remove OpenAlex wildcard characters, which its ``search`` parameter rejects."""
    return " ".join(query.translate({ord("?"): " ", ord("*"): " "}).split())


class _SparseCapableEmbedder(VectorEmbedder, Protocol):
    async def encode_papers(
        self, texts: Sequence[str]
    ) -> tuple[tuple[object, tuple[str, ...]], ...]: ...


class SpendLedger:
    """Atomically reserve run and UTC-day spend before external requests."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def reserve(
        self,
        *,
        run_id: UUID | None,
        kind: SpendKind,
        cost_usd: Decimal,
        run_limit: int | None,
        daily_cap_usd: Decimal,
    ) -> None:
        if run_id is not None and not isinstance(run_id, UUID):
            raise ValueError("run_id must be a UUID or None")
        if kind not in {"search_request", "content_download"}:
            raise ValueError("unsupported discovery spend kind")
        if (
            not isinstance(cost_usd, Decimal)
            or not cost_usd.is_finite()
            or cost_usd <= 0
        ):
            raise ValueError("cost_usd must be a finite positive Decimal")
        cost_exponent = cost_usd.as_tuple().exponent
        if (
            isinstance(cost_exponent, int)
            and cost_exponent < -4
            or cost_usd > Decimal("9999.9999")
        ):
            raise ValueError("cost_usd must fit discovery_spend numeric(8, 4)")
        if run_limit is not None and (
            isinstance(run_limit, bool)
            or not isinstance(run_limit, int)
            or run_limit <= 0
        ):
            raise ValueError("run_limit must be a positive integer or None")
        if (
            not isinstance(daily_cap_usd, Decimal)
            or not daily_cap_usd.is_finite()
            or daily_cap_usd <= 0
        ):
            raise ValueError("daily_cap_usd must be a finite positive Decimal")

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                # Serialize both the run counter and global daily sum so concurrent
                # processes cannot reserve the same remaining budget.
                await connection.fetchval(
                    "SELECT pg_advisory_xact_lock(hashtextextended('discovery-spend', 0))"
                )
                spend_date = await connection.fetchval(
                    "SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date"
                )
                if spend_date is None:
                    raise RuntimeError("database did not return the UTC spend date")

                if run_id is not None and run_limit is not None:
                    request_count = await connection.fetchval(
                        """
                        SELECT count(*)
                        FROM discovery_spend
                        WHERE run_id = $1 AND kind = $2
                        """,
                        run_id,
                        kind,
                    )
                    if int(cast(int, request_count)) >= run_limit:
                        raise DiscoveryBudgetExceeded("run_search_limit")

                spent_value = await connection.fetchval(
                    """
                    SELECT COALESCE(sum(cost_usd), 0)::numeric
                    FROM discovery_spend
                    WHERE spend_date = $1
                    """,
                    spend_date,
                )
                spent = Decimal(str(spent_value or "0"))
                if spent + cost_usd > daily_cap_usd:
                    raise DiscoveryBudgetExceeded("daily_spend_cap")

                await connection.execute(
                    """
                    INSERT INTO discovery_spend (spend_date, run_id, kind, cost_usd)
                    VALUES ($1, $2, $3, $4)
                    """,
                    spend_date,
                    run_id,
                    kind,
                    cost_usd,
                )


class OnlineDiscovery:
    """Search OpenAlex, persist catalog metadata and rank paper vectors."""

    def __init__(
        self,
        *,
        openalex: OpenAlexClient,
        catalog: CatalogRepository,
        papers: GenerationQdrantCollection,
        embedder: VectorEmbedder,
        configuration: GenerationIndexConfiguration,
        ledger: SpendLedger,
        settings: DiscoverySettings,
    ) -> None:
        if openalex.results_per_request != settings.results_per_request:
            raise ValueError(
                "OpenAlex client page size must match DiscoverySettings.results_per_request"
            )
        self.openalex = openalex
        self.catalog = catalog
        self.papers = papers
        self.embedder = embedder
        self.configuration = configuration
        self.ledger = ledger
        self.settings = settings

    async def discover(
        self,
        *,
        run_id: UUID | None,
        question: str,
        query: str,
        year_from: int | None = None,
        year_to: int | None = None,
        limit: int = 10,
    ) -> tuple[DiscoveredPaper, ...]:
        _require_text(question, "question")
        _require_text(query, "query")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        for name, value in (("year_from", year_from), ("year_to", year_to)):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= 9999
            ):
                raise ValueError(f"{name} must be an integer from 1 through 9999")
        if year_from is not None and year_to is not None and year_from > year_to:
            raise ValueError("year_from must be less than or equal to year_to")

        first_year = max(
            self.settings.minimum_publication_year,
            self.settings.minimum_publication_year if year_from is None else year_from,
        )
        last_year = year_to
        if last_year is None:
            last_year = max(datetime.now(UTC).year, first_year)
        if last_year < first_year:
            return ()

        extra_filter = ",".join(
            (
                f"publication_year:{first_year}-{last_year}",
                "primary_topic.field.id:"
                + "|".join(
                    field_id.removeprefix("fields/")
                    for field_id in self.settings.openalex_field_ids
                ),
            )
        )
        search_query = openalex_search_query(query)
        if not search_query:
            return ()
        works = await self._search_works(
            run_id=run_id,
            query=search_query,
            extra_filter=extra_filter,
            limit=self.settings.results_per_request,
        )
        if not works:
            return ()

        indexed: list[PaperIndexInput] = []
        for work in works:
            upsert = await self.catalog.upsert_openalex_work(work, work.metadata)
            indexed.append(
                PaperIndexInput(
                    paper_id=upsert.paper_id,
                    title=work.title,
                    abstract=abstract_from_openalex_metadata(work.metadata),
                    publication_year=work.publication_year,
                    openalex_id=work.openalex_id,
                    doi=work.doi,
                )
            )

        with_text = tuple(paper for paper in indexed if paper.index_text)
        if not with_text:
            return ()

        point_ids = tuple(
            paper_point_id(paper.paper_id, self.configuration.configuration_id)
            for paper in with_text
        )
        existing = {
            match.point_id: match.payload
            for match in await self.papers.retrieve(point_ids)
        }
        sparse_encoder: SparsePaperEncoder | None = None
        if self.configuration.lexical is not None:
            encoder = cast(_SparseCapableEmbedder, self.embedder)
            if not callable(getattr(encoder, "encode_papers", None)):
                raise ValueError(
                    "the configured embedder must also encode sparse paper vectors"
                )
            sparse_encoder = cast(SparsePaperEncoder, encoder)

        for start in range(0, len(with_text), self.configuration.batch_size):
            batch = with_text[start : start + self.configuration.batch_size]
            dense_vectors = await self.embedder.embed(
                [paper.index_text for paper in batch],
                configuration=self.configuration.dense_configuration(),
            )
            if len(dense_vectors) != len(batch):
                raise ValueError("embedding adapter returned a different item count")
            sparse_values = (
                await sparse_encoder.encode_papers(
                    [paper_lexical_text(paper.title) for paper in batch]
                )
                if sparse_encoder is not None
                else None
            )
            points: list[GenerationPoint] = []
            for offset, (paper, dense) in enumerate(
                zip(batch, dense_vectors, strict=True)
            ):
                point_id = point_ids[start + offset]
                old_payload = existing.get(point_id, {})
                old_status = old_payload.get("catalog_status", "metadata_only")
                if old_status not in {"ingested", "metadata_only"}:
                    raise ValueError("existing paper has an invalid catalog status")
                old_generation = old_payload.get("indexed_generation")
                if old_generation is not None and (
                    isinstance(old_generation, bool)
                    or not isinstance(old_generation, int)
                    or old_generation <= 0
                ):
                    raise ValueError("existing paper has an invalid indexed_generation")
                payload = paper_payload(
                    paper,
                    self.configuration,
                    catalog_status=old_status,
                    indexed_generation=old_generation,
                )
                sparse_vector = None
                if sparse_values is not None:
                    sparse_vector, lexical_terms = sparse_values[offset]
                    payload["lexical_terms"] = list(lexical_terms)
                points.append(
                    GenerationPoint(
                        point_id=point_id,
                        dense=dense,
                        sparse=sparse_vector,
                        payload=payload,
                    )
                )
            await self.papers.upsert(points)

        question_vectors = await self.embedder.embed(
            [question], configuration=self.configuration.dense_configuration()
        )
        if len(question_vectors) != 1:
            raise ValueError("embedding adapter returned a different item count")
        paper_ids = [paper.paper_id for paper in with_text]
        matches = await self.papers.query_dense(
            question_vectors[0],
            filter_={"must": [{"key": "paper_id", "match": {"any": paper_ids}}]},
            limit=len(paper_ids),
        )
        papers_by_id = {paper.paper_id: paper for paper in with_text}
        ranked = sorted(
            matches,
            key=lambda match: (
                -match.score,
                str(match.payload.get("paper_id", "")),
            ),
        )
        discovered: list[DiscoveredPaper] = []
        for match in ranked[:limit]:
            paper_id_value = match.payload.get("paper_id")
            if not isinstance(paper_id_value, str):
                raise ValueError("Qdrant paper match has no paper_id payload")
            matched_paper = papers_by_id.get(paper_id_value)
            if matched_paper is None:
                continue
            status = match.payload.get("catalog_status", "metadata_only")
            if status not in {"ingested", "metadata_only"}:
                raise ValueError("Qdrant paper match has an invalid catalog status")
            discovered.append(
                DiscoveredPaper(
                    paper_id=matched_paper.paper_id,
                    openalex_id=matched_paper.openalex_id or "",
                    title=matched_paper.title,
                    publication_year=matched_paper.publication_year,
                    abstract=matched_paper.abstract,
                    similarity=match.score,
                    catalog_status=status,
                )
            )
        return tuple(discovered)

    async def _search_works(
        self,
        *,
        run_id: UUID | None,
        query: str,
        extra_filter: str,
        limit: int,
    ) -> tuple[OpenAlexWork, ...]:
        reserved_attempts = 0

        async def reserve_request() -> None:
            nonlocal reserved_attempts
            if reserved_attempts >= self.settings.max_search_requests_per_run:
                raise DiscoveryBudgetExceeded("run_search_limit")
            await self.ledger.reserve(
                run_id=run_id,
                kind="search_request",
                cost_usd=self.settings.search_request_cost_usd,
                run_limit=self.settings.max_search_requests_per_run,
                daily_cap_usd=self.settings.daily_spend_cap_usd,
            )
            reserved_attempts += 1

        cursor = "*"
        seen: set[str] = set()
        results: list[OpenAlexWork] = []
        while True:
            with self.openalex.request_reservation_scope(reserve_request):
                page = await self.openalex.search_page(
                    query, cursor, extra_filter=extra_filter
                )
            for work in page.results:
                if work.openalex_id in seen:
                    continue
                seen.add(work.openalex_id)
                results.append(work)
                if len(results) >= limit:
                    break
            if len(results) >= limit or page.next_cursor is None:
                break
            cursor = page.next_cursor
        return tuple(results)


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
