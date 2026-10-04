"""PostgreSQL repository for research run lifecycle and results."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, NoReturn, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimResult,
    EvidenceCitation,
    FailureCategory,
    PaperSummary,
    ResearchMode,
    ResearchRequest,
    ResearchRunView,
    RunProvenance,
    RunStatus,
    RunUsage,
    SupportLabel,
)


class RunNotFound(LookupError):
    """A requested research run does not exist."""


class InvalidRunTransition(RuntimeError):
    """A run lifecycle operation is invalid for its current status."""


@dataclass(frozen=True)
class StoredRun:
    """Persisted request and lifecycle fields for a research run."""

    run_id: UUID
    status: RunStatus
    mode: ResearchMode
    request: ResearchRequest
    snapshot_id: UUID | None
    configuration_id: str | None
    resume_count: int
    active_seconds: float
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class ToolCallRecord:
    """Compact, text-free record of a tool invocation."""

    ordinal: int
    tool_name: str
    arguments: Mapping[str, object]
    status: Literal["succeeded", "failed", "rejected", "cached"]
    result_summary: Mapping[str, object]
    duration_ms: float
    error_category: str | None = None


@dataclass(frozen=True)
class EvidenceRecord:
    """Passage copied into a run so resumed synthesis uses stable evidence."""

    handle: str
    chunk_id: str
    paper_id: str
    text: str
    metadata: Mapping[str, object]


class RunRepository:
    """Asyncpg persistence adapter for all research run records."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_run(
        self, request: ResearchRequest, *, generation: int | None = None
    ) -> UUID:
        """Store a queued run, pinned to ``generation`` when one is served."""
        async with self._pool.acquire() as connection:
            run_id = await connection.fetchval(
                """
                INSERT INTO research_runs
                    (question, status, mode, request, snapshot_id, generation)
                VALUES ($1, 'queued', $2, $3::jsonb, $4, $5)
                RETURNING id
                """,
                request.question,
                request.mode.value,
                _request_json(request),
                request.snapshot_id,
                generation,
            )
        return cast(UUID, run_id)

    async def get_run(self, run_id: UUID) -> StoredRun:
        """Read the persisted request and lifecycle fields."""
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT id, status, mode, request, snapshot_id, configuration_id,
                       resume_count, active_seconds, created_at, started_at, completed_at
                FROM research_runs
                WHERE id = $1
                """,
                run_id,
            )
        if row is None:
            raise RunNotFound(f"run {run_id} was not found")
        return _stored_run(row)

    async def list_runs(
        self, statuses: Sequence[RunStatus], *, limit: int = 100
    ) -> tuple[StoredRun, ...]:
        """List newest runs whose current status is included in ``statuses``."""
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        status_values = [status.value for status in statuses]
        if any(not isinstance(status, RunStatus) for status in statuses):
            raise ValueError("statuses must contain RunStatus values")
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT id, status, mode, request, snapshot_id, configuration_id,
                       resume_count, active_seconds, created_at, started_at, completed_at
                FROM research_runs
                WHERE status = ANY($1::text[])
                ORDER BY created_at DESC, id DESC
                LIMIT $2
                """,
                status_values,
                limit,
            )
        return tuple(_stored_run(row) for row in rows)

    async def mark_running(self, run_id: UUID, *, provenance: RunProvenance) -> None:
        """Start or resume a queued/running run and record effective provenance."""
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE research_runs
                SET status = 'running', snapshot_id = $2, configuration_id = $3,
                    provenance = $4::jsonb, trace_id = $5,
                    started_at = COALESCE(started_at, now()), updated_at = now()
                WHERE id = $1 AND status IN ('queued', 'running')
                RETURNING id
                """,
                run_id,
                provenance.snapshot_id,
                provenance.configuration_id,
                _provenance_json(provenance),
                provenance.trace_id,
            )
            if row is None:
                await _raise_transition(connection, run_id, "mark running")

    async def record_resume(self, run_id: UUID) -> int:
        """Increment and return the resume count for a running run."""
        async with self._pool.acquire() as connection:
            count = await connection.fetchval(
                """
                UPDATE research_runs
                SET resume_count = resume_count + 1, updated_at = now()
                WHERE id = $1 AND status = 'running'
                RETURNING resume_count
                """,
                run_id,
            )
            if count is None:
                await _raise_transition(connection, run_id, "record resume")
        return cast(int, count)

    async def add_active_seconds(self, run_id: UUID, seconds: float) -> float:
        """Accumulate active execution time and return the new total."""
        _nonnegative_finite(seconds, "seconds")
        async with self._pool.acquire() as connection:
            total = await connection.fetchval(
                """
                UPDATE research_runs
                SET active_seconds = active_seconds + $2, updated_at = now()
                WHERE id = $1 AND status = 'running'
                RETURNING active_seconds
                """,
                run_id,
                seconds,
            )
            if total is None:
                await _raise_transition(connection, run_id, "add active time")
        return cast(float, total)

    async def append_tool_call(self, run_id: UUID, record: ToolCallRecord) -> None:
        """Insert a tool call once, keyed by its run-local ordinal."""
        if record.ordinal < 0:
            raise ValueError("ordinal must be non-negative")
        if not record.tool_name.strip():
            raise ValueError("tool_name must be non-empty")
        _nonnegative_finite(record.duration_ms, "duration_ms")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO tool_calls
                        (run_id, ordinal, tool_name, arguments, result, status,
                         duration_ms, error_category)
                    VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8)
                    ON CONFLICT (run_id, ordinal) DO NOTHING
                    """,
                    run_id,
                    record.ordinal,
                    record.tool_name,
                    _mapping_json(record.arguments),
                    _mapping_json(record.result_summary),
                    record.status,
                    record.duration_ms,
                    record.error_category,
                )
                await connection.execute(
                    "UPDATE research_runs SET updated_at = now() WHERE id = $1",
                    run_id,
                )

    async def save_evidence(
        self, run_id: UUID, records: Sequence[EvidenceRecord]
    ) -> None:
        """Copy evidence passages into the run, ignoring replayed writes."""
        if not records:
            return
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.executemany(
                    """
                    INSERT INTO research_run_evidence
                        (run_id, handle, chunk_id, paper_id, text, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        (
                            run_id,
                            record.handle,
                            record.chunk_id,
                            record.paper_id,
                            record.text,
                            _mapping_json(record.metadata),
                        )
                        for record in records
                    ],
                )
                await connection.execute(
                    "UPDATE research_runs SET updated_at = now() WHERE id = $1",
                    run_id,
                )

    async def load_evidence(
        self, run_id: UUID, handles: Sequence[str] | None = None
    ) -> dict[str, EvidenceRecord]:
        """Load all copied evidence or only the requested run-local handles."""
        if handles is not None and not handles:
            return {}
        async with self._pool.acquire() as connection:
            if handles is None:
                rows = await connection.fetch(
                    """
                    SELECT handle, chunk_id, paper_id, text, metadata
                    FROM research_run_evidence
                    WHERE run_id = $1
                    ORDER BY created_at, handle
                    """,
                    run_id,
                )
            else:
                rows = await connection.fetch(
                    """
                    SELECT handle, chunk_id, paper_id, text, metadata
                    FROM research_run_evidence
                    WHERE run_id = $1 AND handle = ANY($2::text[])
                    ORDER BY created_at, handle
                    """,
                    run_id,
                    list(handles),
                )
        return {
            row["handle"]: EvidenceRecord(
                handle=row["handle"],
                chunk_id=row["chunk_id"],
                paper_id=row["paper_id"],
                text=row["text"],
                metadata=_json_mapping(row["metadata"]),
            )
            for row in rows
        }

    async def complete_run(
        self,
        run_id: UUID,
        *,
        answer: str,
        outcome: AnswerOutcome,
        claims: Sequence[ClaimResult],
        usage: RunUsage,
    ) -> None:
        """Atomically replace claims and finish a running run."""
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                status = await connection.fetchval(
                    "SELECT status FROM research_runs WHERE id = $1 FOR UPDATE",
                    run_id,
                )
                if status is None:
                    raise RunNotFound(f"run {run_id} was not found")
                if status != RunStatus.RUNNING.value:
                    raise InvalidRunTransition(
                        f"cannot complete run {run_id} from status {status}"
                    )
                await _validate_claim_evidence(connection, run_id, claims)
                await connection.execute("DELETE FROM claims WHERE run_id = $1", run_id)
                for ordinal, claim in enumerate(claims, start=1):
                    claim_id = await connection.fetchval(
                        """
                        INSERT INTO claims (run_id, claim_text, ordinal, support, quote)
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING id
                        """,
                        run_id,
                        claim.text,
                        ordinal,
                        claim.support.value,
                        claim.quote,
                    )
                    await connection.executemany(
                        """
                        INSERT INTO claim_evidence (claim_id, chunk_id, handle)
                        VALUES ($1, $2, $3)
                        """,
                        [
                            (claim_id, citation.chunk_id, citation.handle)
                            for citation in claim.evidence
                        ],
                    )
                await connection.execute(
                    """
                    UPDATE research_runs
                    SET status = 'completed', answer = $2, answer_outcome = $3,
                        usage = $4::jsonb, error_message = NULL,
                        failure_category = NULL, completed_at = now(), updated_at = now()
                    WHERE id = $1
                    """,
                    run_id,
                    answer,
                    outcome.value,
                    _usage_json(usage),
                )

    async def fail_run(
        self,
        run_id: UUID,
        *,
        category: FailureCategory,
        message: str,
        usage: RunUsage,
    ) -> None:
        """Fail a queued or running run with a bounded error message."""
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE research_runs
                SET status = 'failed', error_message = $2, failure_category = $3,
                    answer_outcome = NULL, usage = $4::jsonb,
                    completed_at = now(), updated_at = now()
                WHERE id = $1 AND status IN ('queued', 'running')
                RETURNING id
                """,
                run_id,
                _truncate_message(message),
                category.value,
                _usage_json(usage),
            )
            if row is None:
                await _raise_transition(connection, run_id, "fail")

    async def get_run_view(self, run_id: UUID) -> ResearchRunView:
        """Build the public run response from its authoritative records."""
        async with self._pool.acquire() as connection:
            run_row = await connection.fetchrow(
                """
                SELECT id, question, status, mode, answer, answer_outcome,
                       failure_category, error_message, provenance, usage,
                       created_at, completed_at
                FROM research_runs
                WHERE id = $1
                """,
                run_id,
            )
            if run_row is None:
                raise RunNotFound(f"run {run_id} was not found")
            claim_rows = await connection.fetch(
                """
                SELECT claim.ordinal, claim.claim_text, claim.support, claim.quote,
                       evidence.handle, evidence.chunk_id, evidence.paper_id,
                       evidence.metadata
                FROM claims AS claim
                LEFT JOIN claim_evidence AS mapping ON mapping.claim_id = claim.id
                LEFT JOIN research_run_evidence AS evidence
                  ON evidence.run_id = claim.run_id
                 AND evidence.handle = mapping.handle
                 AND evidence.chunk_id = mapping.chunk_id
                WHERE claim.run_id = $1
                ORDER BY claim.ordinal,
                         substring(mapping.handle FROM 2)::integer NULLS LAST
                """,
                run_id,
            )

        claims_by_ordinal: dict[int, dict[str, object]] = {}
        papers: dict[str, PaperSummary] = {}
        for row in claim_rows:
            ordinal = row["ordinal"]
            grouped = claims_by_ordinal.setdefault(
                ordinal,
                {
                    "text": row["claim_text"],
                    "quote": row["quote"],
                    "support": row["support"],
                    "evidence": [],
                },
            )
            if row["handle"] is None:
                continue
            citations = grouped["evidence"]
            assert isinstance(citations, list)
            citation = EvidenceCitation(
                handle=row["handle"],
                chunk_id=row["chunk_id"],
                paper_id=row["paper_id"],
            )
            citations.append(citation)
            metadata = _json_mapping(row["metadata"])
            paper_id = row["paper_id"]
            papers.setdefault(
                paper_id,
                PaperSummary(
                    paper_id=paper_id,
                    title=_optional_string(metadata.get("title")),
                    publication_year=_optional_int(metadata.get("publication_year")),
                ),
            )

        claims = tuple(
            ClaimResult(
                claim_id=f"claim-{ordinal}",
                text=str(values["text"]),
                quote=_optional_string(values["quote"]),
                evidence=tuple(values["evidence"]),  # type: ignore[arg-type]
                support=SupportLabel(str(values["support"])),
            )
            for ordinal, values in sorted(claims_by_ordinal.items())
        )
        provenance = _provenance_from_json(run_row["provenance"])
        return ResearchRunView(
            run_id=run_row["id"],
            status=RunStatus(run_row["status"]),
            mode=ResearchMode(run_row["mode"]),
            question=run_row["question"],
            answer=run_row["answer"],
            answer_outcome=(
                AnswerOutcome(run_row["answer_outcome"])
                if run_row["answer_outcome"] is not None
                else None
            ),
            claims=claims,
            papers=tuple(papers.values()),
            failure_category=(
                FailureCategory(run_row["failure_category"])
                if run_row["failure_category"] is not None
                else None
            ),
            error_message=run_row["error_message"],
            provenance=provenance,
            usage=_usage_from_json(run_row["usage"]),
            created_at=run_row["created_at"],
            completed_at=run_row["completed_at"],
        )

    async def prune(self, *, older_than: timedelta) -> tuple[UUID, ...]:
        """Delete old terminal runs and return the removed IDs."""
        if older_than <= timedelta(0):
            raise ValueError("older_than must be positive")
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                DELETE FROM research_runs
                WHERE status IN ('completed', 'failed')
                  AND completed_at < now() - $1::interval
                RETURNING id
                """,
                older_than,
            )
        return tuple(row["id"] for row in rows)


async def _raise_transition(
    connection: asyncpg.Connection, run_id: UUID, operation: str
) -> NoReturn:
    status = await connection.fetchval(
        "SELECT status FROM research_runs WHERE id = $1", run_id
    )
    if status is None:
        raise RunNotFound(f"run {run_id} was not found")
    raise InvalidRunTransition(f"cannot {operation} run {run_id} from status {status}")


async def _validate_claim_evidence(
    connection: asyncpg.Connection, run_id: UUID, claims: Sequence[ClaimResult]
) -> None:
    requested: dict[str, tuple[str, str]] = {}
    for claim in claims:
        for citation in claim.evidence:
            identity = (citation.chunk_id, citation.paper_id)
            previous = requested.setdefault(citation.handle, identity)
            if previous != identity:
                raise ValueError(
                    "one evidence handle cannot identify multiple passages"
                )
    if not requested:
        return
    rows = await connection.fetch(
        """
        SELECT handle, chunk_id, paper_id
        FROM research_run_evidence
        WHERE run_id = $1 AND handle = ANY($2::text[])
        """,
        run_id,
        list(requested),
    )
    stored = {row["handle"]: (row["chunk_id"], row["paper_id"]) for row in rows}
    if stored != requested:
        raise ValueError("claim evidence must match evidence stored for this run")


def _stored_run(row: asyncpg.Record) -> StoredRun:
    request = _request_from_json(row["request"])
    return StoredRun(
        run_id=row["id"],
        status=RunStatus(row["status"]),
        mode=ResearchMode(row["mode"]),
        request=request,
        snapshot_id=row["snapshot_id"],
        configuration_id=row["configuration_id"],
        resume_count=row["resume_count"],
        active_seconds=row["active_seconds"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def _request_json(request: ResearchRequest) -> str:
    return request.model_dump_json()


def _request_from_json(value: object) -> ResearchRequest:
    return ResearchRequest.model_validate_json(_json_text(value))


def _usage_json(usage: RunUsage) -> str:
    return usage.model_dump_json()


def _usage_from_json(value: object) -> RunUsage:
    return RunUsage.model_validate_json(_json_text(value))


def _provenance_json(provenance: RunProvenance) -> str:
    return provenance.model_dump_json()


def _provenance_from_json(value: object) -> RunProvenance | None:
    if value is None:
        return None
    return RunProvenance.model_validate_json(_json_text(value))


def _mapping_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _json_mapping(value: object) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("stored JSON value must be an object")
    return dict(value)


def _truncate_message(message: str) -> str:
    return message[:500]


def _nonnegative_finite(value: float, name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
