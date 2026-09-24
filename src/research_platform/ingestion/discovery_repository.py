"""PostgreSQL persistence for replayable discovery runs and review manifests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.config import DiscoveryConfig
from research_platform.ingestion.openalex import DiscoveryPage, OpenAlexWork

ManifestDecision = Literal["include", "exclude"]
ManifestReviewState = Literal["undecided", "include", "exclude"]
ManifestStatus = Literal["draft", "approved"]
CoverageQuestion = Literal["hybrid_dense", "reranking_latency", "chunking_citation"]
CoverageStatus = Literal["covered", "gap"]
RunStatus = Literal["pending", "running", "paused", "completed", "failed"]


class RequestBudgetExceeded(RuntimeError):
    """The persistent per-run external request ceiling has been reached."""


@dataclass(frozen=True)
class DiscoveryResumePoint:
    query_index: int
    cursor: str
    pages_completed: int


@dataclass(frozen=True)
class ManifestHeader:
    id: UUID
    run_id: UUID
    version: int
    status: ManifestStatus
    configuration_id: str
    code_revision: str


@dataclass(frozen=True)
class ManifestDecisionEntry:
    openalex_id: str
    decision: ManifestDecision
    reason: str
    coverage_questions: tuple[CoverageQuestion, ...]


@dataclass(frozen=True)
class ManifestCoverageEntry:
    question: CoverageQuestion
    status: CoverageStatus
    reviewer_note: str


@dataclass(frozen=True)
class ManifestCoverageReview:
    question: CoverageQuestion
    status: CoverageStatus
    reviewer_note: str


@dataclass(frozen=True)
class ManifestItem:
    openalex_id: str
    title: str | None
    publication_year: int | None
    language: str | None
    work_type: str | None
    decision: ManifestReviewState
    reason: str | None
    selection_signals: Mapping[str, object]
    metadata: Mapping[str, object]
    origins: tuple[Mapping[str, object], ...]
    coverage_questions: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryQuerySummary:
    query_index: int
    query_text: str
    source_kind: str
    page_count: int
    result_count: int
    truncated: bool


@dataclass(frozen=True)
class DiscoveryRunSummary:
    id: UUID
    status: RunStatus
    request_count: int
    result_count: int
    api_cost_usd: float
    configuration: Mapping[str, object]
    queries: tuple[DiscoveryQuerySummary, ...]


class DiscoveryRepository:
    """Persist source responses and reviewer decisions through one pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_run(
        self,
        configuration: DiscoveryConfig,
        code_revision: str,
    ) -> UUID:
        """Create a run and its ordered query checkpoints."""
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                run_id = await connection.fetchval(
                    """
                    INSERT INTO discovery_runs
                        (configuration_id, configuration, code_revision, status)
                    VALUES ($1, $2::jsonb, $3, 'pending')
                    RETURNING id
                    """,
                    configuration.config_id,
                    json.dumps(configuration.to_dict(), sort_keys=True),
                    code_revision,
                )
                query_sources: list[tuple[int, str, str, str | None]] = [
                    (index, query, "search", None)
                    for index, query in enumerate(configuration.queries)
                ]
                query_sources.extend(
                    (
                        len(configuration.queries) + exception_index,
                        f"older_exception:{openalex_id}",
                        "exception",
                        openalex_id,
                    )
                    for exception_index, openalex_id in enumerate(
                        configuration.older_paper_exceptions
                    )
                )
                for query_index, query_text, source_kind, exception_id in query_sources:
                    await connection.execute(
                        """
                        INSERT INTO discovery_queries
                            (run_id, query_index, query_text, source_kind,
                             exception_openalex_id)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        run_id,
                        query_index,
                        query_text,
                        source_kind,
                        exception_id,
                    )
        if not isinstance(run_id, UUID):
            raise RuntimeError("database did not return a discovery run ID")
        return run_id

    async def start_run(self, run_id: UUID, configuration_id: str) -> None:
        async with self._pool.acquire() as connection:
            updated = await connection.fetchval(
                """
                UPDATE discovery_runs
                SET status = 'running', started_at = COALESCE(started_at, now())
                WHERE id = $1
                    AND configuration_id = $2
                    AND status IN ('pending', 'paused', 'running')
                RETURNING id
                """,
                run_id,
                configuration_id,
            )
        if updated is None:
            raise ValueError("discovery run is missing, incompatible, or terminal")

    async def reserve_request(self, run_id: UUID, request_limit: int) -> None:
        """Atomically reserve one HTTP attempt before sending it."""
        async with self._pool.acquire() as connection:
            request_count = await connection.fetchval(
                """
                UPDATE discovery_runs
                SET request_count = request_count + 1
                WHERE id = $1
                    AND status = 'running'
                    AND request_count < $2
                RETURNING request_count
                """,
                run_id,
                request_limit,
            )
        if request_count is None:
            raise RequestBudgetExceeded(
                "discovery run is not running or its request limit is reached"
            )

    async def save_page(
        self,
        run_id: UUID,
        page: DiscoveryPage,
        configuration: DiscoveryConfig,
    ) -> bool:
        """Atomically store a page, candidates, origins and next cursor."""
        query_is_complete = (
            page.page.next_cursor is None
            or page.page_number >= configuration.limits.max_pages_per_query
        )
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                inserted_page = await connection.fetchval(
                    """
                    INSERT INTO discovery_pages
                        (run_id, query_index, page_number, cursor_used, next_cursor,
                         result_count, api_cost_usd, source_metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                    ON CONFLICT (run_id, query_index, page_number) DO NOTHING
                    RETURNING run_id
                    """,
                    run_id,
                    page.query_index,
                    page.page_number,
                    page.cursor_used,
                    page.page.next_cursor,
                    len(page.page.results),
                    page.page.api_cost_usd,
                    json.dumps(dict(page.page.source_metadata), sort_keys=True),
                )
                if inserted_page is None:
                    return False

                for page_rank, work in enumerate(page.page.results, start=1):
                    rank = (
                        page.page_number - 1
                    ) * configuration.limits.per_page + page_rank
                    candidate_id = await self._save_candidate(
                        connection,
                        run_id,
                        work,
                        configuration,
                    )
                    await connection.execute(
                        """
                        INSERT INTO discovery_candidate_origins
                            (run_id, candidate_id, query_index, rank,
                             relevance_score, source_page)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (candidate_id, query_index) DO NOTHING
                        """,
                        run_id,
                        candidate_id,
                        page.query_index,
                        rank,
                        work.relevance_score,
                        page.page_number,
                    )

                await connection.execute(
                    """
                    UPDATE discovery_queries
                    SET next_cursor = COALESCE($3, next_cursor),
                        page_count = $4,
                        completed = $5,
                        truncated = $6,
                        result_count = result_count + $7
                    WHERE run_id = $1 AND query_index = $2
                    """,
                    run_id,
                    page.query_index,
                    page.page.next_cursor,
                    page.page_number,
                    query_is_complete,
                    page.page.next_cursor is not None and query_is_complete,
                    len(page.page.results),
                )
                await connection.execute(
                    """
                    UPDATE discovery_runs
                    SET result_count = (
                            SELECT count(*) FROM discovery_candidates WHERE run_id = $1
                        ),
                        api_cost_usd = api_cost_usd + $2
                    WHERE id = $1
                    """,
                    run_id,
                    page.page.api_cost_usd,
                )
        return True

    async def resume_points(self, run_id: UUID) -> tuple[DiscoveryResumePoint, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT query_index, next_cursor, page_count
                FROM discovery_queries
                WHERE run_id = $1 AND completed = FALSE
                ORDER BY query_index
                """,
                run_id,
            )
        return tuple(
            DiscoveryResumePoint(
                query_index=row["query_index"],
                cursor=row["next_cursor"],
                pages_completed=row["page_count"],
            )
            for row in rows
        )

    async def set_run_status(
        self, run_id: UUID, status: RunStatus, error_message: str | None = None
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE discovery_runs
                SET status = $2,
                    completed_at = CASE
                        WHEN $2 IN ('completed', 'failed') THEN now()
                        ELSE NULL
                    END,
                    error_message = $3
                WHERE id = $1
                """,
                run_id,
                status,
                error_message,
            )

    async def create_manifest(self, run_id: UUID, version: int) -> UUID:
        async with self._pool.acquire() as connection:
            manifest_id = await connection.fetchval(
                """
                INSERT INTO discovery_manifests (run_id, version)
                VALUES ($1, $2)
                RETURNING id
                """,
                run_id,
                version,
            )
        if not isinstance(manifest_id, UUID):
            raise RuntimeError("database did not return a manifest ID")
        return manifest_id

    async def prepare_shortlist_manifest(
        self, run_id: UUID, version: int, per_query_limit: int = 50
    ) -> UUID:
        """Create a draft of top-ranked candidates for human review."""
        if version <= 0:
            raise ValueError("manifest version must be positive")
        if per_query_limit <= 0:
            raise ValueError("per_query_limit must be positive")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                manifest_id = await connection.fetchval(
                    """
                    INSERT INTO discovery_manifests (run_id, version)
                    VALUES ($1, $2)
                    RETURNING id
                    """,
                    run_id,
                    version,
                )
                await connection.execute(
                    """
                    WITH ranked AS (
                        SELECT origin.candidate_id,
                               query.source_kind,
                               row_number() OVER (
                                   PARTITION BY origin.query_index
                                   ORDER BY origin.rank ASC NULLS LAST,
                                            origin.relevance_score DESC NULLS LAST,
                                            candidate.cited_by_count DESC NULLS LAST,
                                            candidate.openalex_id ASC
                               ) AS query_rank
                        FROM discovery_candidate_origins AS origin
                        JOIN discovery_queries AS query
                          ON query.run_id = origin.run_id
                         AND query.query_index = origin.query_index
                        JOIN discovery_candidates AS candidate
                          ON candidate.id = origin.candidate_id
                        WHERE origin.run_id = $1
                    ), selected AS (
                        SELECT DISTINCT candidate_id
                        FROM ranked
                        WHERE source_kind = 'exception' OR query_rank <= $3
                    )
                    INSERT INTO discovery_manifest_items
                        (manifest_id, run_id, candidate_id)
                    SELECT $2, $1, candidate_id FROM selected
                    """,
                    run_id,
                    manifest_id,
                    per_query_limit,
                )
        if not isinstance(manifest_id, UUID):
            raise RuntimeError("database did not return a manifest ID")
        return manifest_id

    async def apply_manifest_review(
        self,
        manifest_id: UUID,
        decisions: tuple[ManifestDecisionEntry, ...],
        coverage_reviews: tuple[ManifestCoverageEntry, ...],
    ) -> None:
        """Apply one complete reviewer file atomically to a draft manifest."""
        candidate_ids = [entry.openalex_id for entry in decisions]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("manifest review contains duplicate candidates")
        if any(not entry.reason.strip() for entry in decisions):
            raise ValueError("every manifest decision needs a reason")
        expected_questions = {
            "hybrid_dense",
            "reranking_latency",
            "chunking_citation",
        }
        coverage_keys = [review.question for review in coverage_reviews]
        if set(coverage_keys) != expected_questions or len(coverage_keys) != 3:
            raise ValueError("review must assess each coverage question exactly once")
        if any(not review.reviewer_note.strip() for review in coverage_reviews):
            raise ValueError("every coverage review needs a note")

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                manifest = await connection.fetchrow(
                    """
                    SELECT run_id FROM discovery_manifests
                    WHERE id = $1 AND status = 'draft'
                    FOR UPDATE
                    """,
                    manifest_id,
                )
                if manifest is None:
                    raise ValueError("manifest is missing or no longer a draft")
                rows = await connection.fetch(
                    """
                    SELECT c.openalex_id, c.id
                    FROM discovery_manifest_items AS i
                    JOIN discovery_candidates AS c ON c.id = i.candidate_id
                    WHERE i.manifest_id = $1
                    """,
                    manifest_id,
                )
                candidate_map = {row["openalex_id"]: row["id"] for row in rows}
                if set(candidate_ids) != set(candidate_map):
                    raise ValueError(
                        "review file must contain every manifest candidate exactly once"
                    )
                for entry in decisions:
                    await connection.execute(
                        """
                        UPDATE discovery_manifest_items
                        SET decision = $3, reason = $4,
                            coverage_questions = $5, reviewed_at = now()
                        WHERE manifest_id = $1 AND candidate_id = $2
                        """,
                        manifest_id,
                        candidate_map[entry.openalex_id],
                        entry.decision,
                        entry.reason.strip(),
                        list(entry.coverage_questions),
                    )
                for review in coverage_reviews:
                    await connection.execute(
                        """
                        INSERT INTO discovery_manifest_coverage
                            (manifest_id, question_key, status, reviewer_note)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (manifest_id, question_key)
                        DO UPDATE SET status = EXCLUDED.status,
                                      reviewer_note = EXCLUDED.reviewer_note,
                                      reviewed_at = now()
                        """,
                        manifest_id,
                        review.question,
                        review.status,
                        review.reviewer_note.strip(),
                    )

    async def set_manifest_item(
        self,
        manifest_id: UUID,
        openalex_id: str,
        decision: ManifestDecision,
        reason: str,
        coverage_questions: tuple[CoverageQuestion, ...] = (),
    ) -> None:
        """Record a human-facing decision against a candidate in the manifest run."""
        if not reason.strip():
            raise ValueError("manifest decision reason must not be empty")
        allowed_coverage = {
            "hybrid_dense",
            "reranking_latency",
            "chunking_citation",
        }
        if not set(coverage_questions) <= allowed_coverage:
            raise ValueError("manifest coverage question is not recognized")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                candidate = await connection.fetchrow(
                    """
                    SELECT m.run_id, c.id
                    FROM discovery_manifests AS m
                    JOIN discovery_candidates AS c ON c.run_id = m.run_id
                    WHERE m.id = $1 AND c.openalex_id = $2 AND m.status = 'draft'
                    """,
                    manifest_id,
                    openalex_id,
                )
                if candidate is None:
                    raise ValueError("candidate is not available in a draft manifest")
                await connection.execute(
                    """
                    INSERT INTO discovery_manifest_items
                        (manifest_id, run_id, candidate_id, decision, reason,
                         coverage_questions, reviewed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, now())
                    ON CONFLICT (manifest_id, candidate_id)
                    DO UPDATE SET decision = EXCLUDED.decision,
                                  reason = EXCLUDED.reason,
                                  coverage_questions = EXCLUDED.coverage_questions,
                                  reviewed_at = now()
                    """,
                    manifest_id,
                    candidate["run_id"],
                    candidate["id"],
                    decision,
                    reason.strip(),
                    list(coverage_questions),
                )

    async def set_manifest_coverage(
        self,
        manifest_id: UUID,
        question: CoverageQuestion,
        status: CoverageStatus,
        reviewer_note: str,
    ) -> None:
        if not reviewer_note.strip():
            raise ValueError("coverage review note must not be empty")
        async with self._pool.acquire() as connection:
            saved = await connection.fetchval(
                """
                INSERT INTO discovery_manifest_coverage
                    (manifest_id, question_key, status, reviewer_note)
                SELECT id, $2, $3, $4
                FROM discovery_manifests
                WHERE id = $1 AND status = 'draft'
                ON CONFLICT (manifest_id, question_key)
                DO UPDATE SET status = EXCLUDED.status,
                              reviewer_note = EXCLUDED.reviewer_note,
                              reviewed_at = now()
                RETURNING manifest_id
                """,
                manifest_id,
                question,
                status,
                reviewer_note.strip(),
            )
        if saved is None:
            raise ValueError("manifest is missing or no longer a draft")

    async def approve_manifest(self, manifest_id: UUID, reviewer: str) -> None:
        if not reviewer.strip():
            raise ValueError("reviewer must not be empty")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                locked_manifest = await connection.fetchval(
                    """
                    SELECT id FROM discovery_manifests
                    WHERE id = $1 AND status = 'draft'
                    FOR UPDATE
                    """,
                    manifest_id,
                )
                if locked_manifest is None:
                    raise ValueError("manifest is missing or already approved")
                review_counts = await connection.fetchrow(
                    """
                    SELECT count(*) AS total,
                           count(*) FILTER (WHERE decision = 'undecided') AS undecided,
                           count(*) FILTER (WHERE decision = 'include') AS included
                    FROM discovery_manifest_items
                    WHERE manifest_id = $1
                    """,
                    manifest_id,
                )
                if review_counts is None or review_counts["total"] == 0:
                    raise ValueError("cannot approve an empty manifest")
                if review_counts["undecided"] > 0 or review_counts["included"] == 0:
                    raise ValueError(
                        "approval requires every decision and at least one inclusion"
                    )
                coverage_count = await connection.fetchval(
                    """
                    SELECT count(*) FROM discovery_manifest_coverage
                    WHERE manifest_id = $1
                    """,
                    manifest_id,
                )
                if coverage_count != 3:
                    raise ValueError(
                        "approval requires a review of all three coverage questions"
                    )
                updated = await connection.fetchval(
                    """
                    UPDATE discovery_manifests
                    SET status = 'approved', approved_at = now(), approved_by = $2
                    WHERE id = $1 AND status = 'draft'
                    RETURNING id
                    """,
                    manifest_id,
                    reviewer.strip(),
                )
                if updated is None:
                    raise ValueError("manifest is missing or already approved")

    async def manifest_header(self, manifest_id: UUID) -> ManifestHeader:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT m.id, m.run_id, m.version, m.status,
                       r.configuration_id, r.code_revision
                FROM discovery_manifests AS m
                JOIN discovery_runs AS r ON r.id = m.run_id
                WHERE m.id = $1
                """,
                manifest_id,
            )
        if row is None:
            raise ValueError("manifest does not exist")
        return ManifestHeader(
            id=row["id"],
            run_id=row["run_id"],
            version=row["version"],
            status=row["status"],
            configuration_id=row["configuration_id"],
            code_revision=row["code_revision"],
        )

    async def run_summary_for_manifest(self, manifest_id: UUID) -> DiscoveryRunSummary:
        """Return bounded-run and per-query diagnostics for shortlist assessment."""
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT run.id, run.status, run.request_count, run.result_count,
                       run.api_cost_usd, run.configuration,
                       query.query_index, query.query_text, query.source_kind,
                       query.page_count, query.result_count AS query_result_count,
                       query.truncated
                FROM discovery_manifests manifest
                JOIN discovery_runs run ON run.id = manifest.run_id
                JOIN discovery_queries query ON query.run_id = run.id
                WHERE manifest.id = $1
                ORDER BY query.query_index
                """,
                manifest_id,
            )
        if not rows:
            raise ValueError("manifest or its discovery run does not exist")
        first = rows[0]
        return DiscoveryRunSummary(
            id=first["id"],
            status=first["status"],
            request_count=first["request_count"],
            result_count=first["result_count"],
            api_cost_usd=float(first["api_cost_usd"]),
            configuration=_as_json_object(first["configuration"]),
            queries=tuple(
                DiscoveryQuerySummary(
                    query_index=row["query_index"],
                    query_text=row["query_text"],
                    source_kind=row["source_kind"],
                    page_count=row["page_count"],
                    result_count=row["query_result_count"],
                    truncated=row["truncated"],
                )
                for row in rows
            ),
        )

    async def list_manifest_coverage(
        self, manifest_id: UUID
    ) -> tuple[ManifestCoverageReview, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT question_key, status, reviewer_note
                FROM discovery_manifest_coverage
                WHERE manifest_id = $1
                ORDER BY question_key
                """,
                manifest_id,
            )
        return tuple(
            ManifestCoverageReview(
                question=row["question_key"],
                status=row["status"],
                reviewer_note=row["reviewer_note"],
            )
            for row in rows
        )

    async def list_manifest_items(self, manifest_id: UUID) -> tuple[ManifestItem, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT c.openalex_id, c.title, c.publication_year, c.language,
                       c.work_type, i.decision, i.reason, c.selection_signals,
                       c.metadata, i.coverage_questions,
                       COALESCE(
                           jsonb_agg(
                               jsonb_build_object(
                                   'query_index', origin.query_index,
                                   'query', q.query_text,
                                   'rank', origin.rank,
                                   'relevance_score', origin.relevance_score,
                                   'source_page', origin.source_page
                               ) ORDER BY origin.query_index
                           ) FILTER (WHERE origin.candidate_id IS NOT NULL),
                           '[]'::jsonb
                       ) AS origins
                FROM discovery_manifest_items AS i
                JOIN discovery_candidates AS c ON c.id = i.candidate_id
                LEFT JOIN discovery_candidate_origins AS origin
                  ON origin.candidate_id = c.id
                LEFT JOIN discovery_queries AS q
                  ON q.run_id = origin.run_id AND q.query_index = origin.query_index
                WHERE i.manifest_id = $1
                GROUP BY c.openalex_id, c.title, c.publication_year, c.language,
                         c.work_type, i.decision, i.reason, c.selection_signals,
                         c.metadata, i.coverage_questions
                ORDER BY c.openalex_id
                """,
                manifest_id,
            )
        return tuple(
            ManifestItem(
                openalex_id=row["openalex_id"],
                title=row["title"],
                publication_year=row["publication_year"],
                language=row["language"],
                work_type=row["work_type"],
                decision=row["decision"],
                reason=row["reason"],
                selection_signals=_as_json_object(row["selection_signals"]),
                metadata=_as_json_object(row["metadata"]),
                origins=tuple(
                    _as_json_object(item) for item in _as_json_array(row["origins"])
                ),
                coverage_questions=tuple(row["coverage_questions"]),
            )
            for row in rows
        )

    async def _save_candidate(
        self,
        connection: asyncpg.Connection,
        run_id: UUID,
        work: OpenAlexWork,
        configuration: DiscoveryConfig,
    ) -> UUID:
        signals = {
            "publication_year_in_range": (
                work.publication_year is not None
                and configuration.year_range.start_year
                <= work.publication_year
                <= configuration.year_range.end_year
            ),
            "older_paper_exception": work.openalex_id
            in configuration.older_paper_exceptions,
            "language_matches": work.language == configuration.language,
            "has_abstract": work.has_abstract,
            "work_type": work.work_type,
            "cited_by_count": work.cited_by_count,
        }
        candidate_id = await connection.fetchval(
            """
            INSERT INTO discovery_candidates
                (run_id, openalex_id, title, publication_year, language, work_type,
                 doi, cited_by_count, metadata, selection_signals)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb)
            ON CONFLICT (run_id, openalex_id) DO UPDATE
                SET title = COALESCE(discovery_candidates.title, EXCLUDED.title),
                    publication_year = COALESCE(
                        discovery_candidates.publication_year,
                        EXCLUDED.publication_year
                    ),
                    language = COALESCE(discovery_candidates.language, EXCLUDED.language),
                    work_type = COALESCE(discovery_candidates.work_type, EXCLUDED.work_type),
                    doi = COALESCE(discovery_candidates.doi, EXCLUDED.doi),
                    cited_by_count = COALESCE(
                        discovery_candidates.cited_by_count,
                        EXCLUDED.cited_by_count
                    )
            RETURNING id
            """,
            run_id,
            work.openalex_id,
            work.title,
            work.publication_year,
            work.language,
            work.work_type,
            work.doi,
            work.cited_by_count,
            json.dumps(dict(work.metadata), sort_keys=True),
            json.dumps(signals, sort_keys=True),
        )
        if not isinstance(candidate_id, UUID):
            raise RuntimeError("database did not return a candidate ID")
        return candidate_id


def _as_json_object(value: object) -> Mapping[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("database JSON object has an unexpected shape")
    return value


def _as_json_array(value: object) -> tuple[object, ...]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise ValueError("database JSON array has an unexpected shape")
    return tuple(value)
