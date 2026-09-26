"""Persist ingestion job ownership and resumable per-document stage attempts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]

JobStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
AttemptStatus = Literal["completed", "failed", "skipped"]
_SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_STAGE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FAILURE_CATEGORY = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ERROR_DETAILS_OMITTED = "details omitted; see failure_category"


class JobStateError(RuntimeError):
    """An ingestion job cannot make the requested ownership/state transition."""


@dataclass(frozen=True)
class IngestionJobSummary:
    id: UUID
    status: JobStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    lease_expires_at: datetime | None
    document_count: int
    completed_documents: int
    failed_documents: int
    running_attempts: int
    failed_attempts: int


@dataclass(frozen=True)
class StageAttempt:
    id: UUID
    job_id: UUID
    document_id: UUID
    stage: str
    attempt_number: int
    configuration_id: str
    input_fingerprint: str
    started_at: datetime
    retry_reason: str | None = None


class IngestionJobRepository:
    """Own job leases, checkpoints and stage outcomes in PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_job(
        self,
        *,
        configuration: Mapping[str, object],
        configuration_id: str,
        code_revision: str,
        execution_profile: str,
        collection_id: UUID | None = None,
        storage_limit_bytes: int | None = None,
    ) -> UUID:
        _validate_identity(configuration_id, "configuration_id")
        for name, value in (
            ("code_revision", code_revision),
            ("execution_profile", execution_profile),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if storage_limit_bytes is not None and (
            isinstance(storage_limit_bytes, bool)
            or not isinstance(storage_limit_bytes, int)
            or storage_limit_bytes <= 0
        ):
            raise ValueError("storage_limit_bytes must be a positive integer or null")
        serialized = json.dumps(dict(configuration), sort_keys=True, ensure_ascii=False)
        async with self._pool.acquire() as connection:
            job_id = await connection.fetchval(
                """
                INSERT INTO ingestion_jobs
                    (collection_id, status, configuration, configuration_id,
                     code_revision, execution_profile, storage_limit_bytes)
                VALUES ($1, 'pending', $2::jsonb, $3, $4, $5, $6)
                RETURNING id
                """,
                collection_id,
                serialized,
                configuration_id,
                code_revision,
                execution_profile,
                storage_limit_bytes,
            )
        if not isinstance(job_id, UUID):
            raise RuntimeError("database did not return an ingestion job ID")
        return job_id

    async def record_plan(
        self,
        job_id: UUID,
        document_inputs: Sequence[tuple[UUID, str]],
        *,
        terminal_stage: str,
        terminal_configuration_id: str,
    ) -> None:
        """Persist and freeze all planned documents and the required final stage."""
        if not document_inputs:
            raise ValueError("an ingestion job plan needs at least one document")
        if not isinstance(terminal_stage, str) or not _STAGE_NAME.fullmatch(
            terminal_stage
        ):
            raise ValueError("terminal_stage must be a lowercase identifier")
        _validate_identity(terminal_configuration_id, "terminal_configuration_id")
        normalized: list[tuple[UUID, str]] = []
        for document_id, input_fingerprint in document_inputs:
            if not isinstance(document_id, UUID):
                raise ValueError("planned document IDs must be UUID values")
            _validate_identity(input_fingerprint, "planned input_fingerprint")
            normalized.append((document_id, input_fingerprint))
        if len({document_id for document_id, _fingerprint in normalized}) != len(
            normalized
        ):
            raise ValueError("an ingestion job plan cannot repeat a document")
        expected_membership = {
            (document_id, fingerprint, terminal_stage)
            for document_id, fingerprint in normalized
        }

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                job = await connection.fetchrow(
                    "SELECT status FROM ingestion_jobs WHERE id = $1 FOR UPDATE",
                    job_id,
                )
                if job is None:
                    raise JobStateError("ingestion job does not exist")
                if job["status"] in {"running", "completed"}:
                    raise JobStateError(
                        "cannot update a plan while a job is running or completed"
                    )
                stored_rows = await connection.fetch(
                    """
                    SELECT document_id, input_fingerprint, terminal_stage,
                           terminal_configuration_id
                    FROM ingestion_job_plan WHERE job_id = $1
                    """,
                    job_id,
                )
                if stored_rows:
                    stored_membership = {
                        (
                            row["document_id"],
                            row["input_fingerprint"],
                            row["terminal_stage"],
                        )
                        for row in stored_rows
                    }
                    if stored_membership != expected_membership:
                        raise JobStateError(
                            "ingestion job plan changed; create a new job"
                        )
                    await connection.execute(
                        """
                        UPDATE ingestion_job_plan
                        SET terminal_configuration_id = $2
                        WHERE job_id = $1
                        """,
                        job_id,
                        terminal_configuration_id,
                    )
                    return
                if job["status"] not in {"pending", "failed", "cancelled"}:
                    raise JobStateError(
                        "cannot add a plan while ingestion is running or completed"
                    )
                for document_id, input_fingerprint in normalized:
                    await connection.execute(
                        """
                        INSERT INTO ingestion_job_plan
                            (job_id, document_id, input_fingerprint, terminal_stage,
                             terminal_configuration_id)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        job_id,
                        document_id,
                        input_fingerprint,
                        terminal_stage,
                        terminal_configuration_id,
                    )
                    await connection.execute(
                        """
                        INSERT INTO ingestion_documents
                            (job_id, document_id, status, stage)
                        VALUES ($1, $2, 'pending', $3)
                        ON CONFLICT (job_id, document_id) DO NOTHING
                        """,
                        job_id,
                        document_id,
                        terminal_stage,
                    )

    async def plan_is_complete(self, job_id: UUID) -> bool:
        """Whether every planned document reached its configured terminal stage."""
        async with self._pool.acquire() as connection:
            incomplete = await connection.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM ingestion_job_plan plan
                    LEFT JOIN ingestion_documents document
                      ON document.job_id = plan.job_id
                     AND document.document_id = plan.document_id
                    WHERE plan.job_id = $1
                      AND (
                          document.status IS DISTINCT FROM 'completed'
                          OR NOT EXISTS (
                              SELECT 1 FROM ingestion_stage_attempts attempt
                              WHERE attempt.job_id = plan.job_id
                                AND attempt.document_id = plan.document_id
                                AND attempt.stage = plan.terminal_stage
                                AND attempt.configuration_id =
                                    plan.terminal_configuration_id
                                AND attempt.status = 'completed'
                          )
                      )
                )
                """,
                job_id,
            )
        return incomplete is False

    async def get_configuration(self, job_id: UUID) -> Mapping[str, object]:
        """Load the non-secret configuration needed to resume a persisted job."""
        async with self._pool.acquire() as connection:
            serialized = await connection.fetchval(
                "SELECT configuration::text FROM ingestion_jobs WHERE id = $1",
                job_id,
            )
        if serialized is None:
            raise JobStateError("ingestion job does not exist")
        configuration = json.loads(serialized)
        if not isinstance(configuration, dict):
            raise JobStateError("stored ingestion configuration is invalid")
        return configuration

    async def claim(self, job_id: UUID, *, lease_seconds: int = 60) -> UUID:
        """Acquire the sole active job lease or reclaim one whose lease expired."""
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int):
            raise ValueError("lease_seconds must be an integer")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                acquired = await connection.fetchval(
                    "SELECT pg_try_advisory_xact_lock(60201, 1)"
                )
                if not acquired:
                    raise JobStateError(
                        "another process is changing ingestion ownership"
                    )
                expired_job_ids = await connection.fetch(
                    """
                    UPDATE ingestion_jobs
                    SET status = 'pending', owner_token = NULL, lease_expires_at = NULL
                    WHERE status = 'running' AND lease_expires_at <= now()
                    RETURNING id
                    """
                )
                for expired_job in expired_job_ids:
                    await connection.execute(
                        """
                        UPDATE ingestion_stage_attempts
                        SET status = 'failed', failure_category = 'lease_expired',
                            error_message = 'job owner lease expired', retryable = TRUE,
                            completed_at = now(),
                            duration_ms = GREATEST(
                                0, floor(extract(epoch FROM (now() - started_at)) * 1000)
                            )::bigint
                        WHERE job_id = $1 AND status = 'running'
                        """,
                        expired_job["id"],
                    )
                    await connection.execute(
                        """
                        UPDATE ingestion_documents
                        SET status = 'failed', error_message = 'job owner lease expired',
                            updated_at = now()
                        WHERE job_id = $1 AND status = 'running'
                        """,
                        expired_job["id"],
                    )
                active_job = await connection.fetchval(
                    """
                    SELECT id FROM ingestion_jobs
                    WHERE status = 'running' AND lease_expires_at > now()
                    LIMIT 1
                    """
                )
                if active_job is not None:
                    raise JobStateError(
                        "another ingestion job currently owns the lease"
                    )
                row = await connection.fetchrow(
                    "SELECT status FROM ingestion_jobs WHERE id = $1 FOR UPDATE",
                    job_id,
                )
                if row is None:
                    raise JobStateError("ingestion job does not exist")
                if row["status"] == "completed":
                    raise JobStateError("a completed ingestion job cannot be resumed")
                owner_token = uuid4()
                claimed = await connection.fetchval(
                    """
                    UPDATE ingestion_jobs
                    SET status = 'running', owner_token = $2,
                        lease_expires_at = now() + ($3 * interval '1 second'),
                        started_at = COALESCE(started_at, now()), completed_at = NULL
                    WHERE id = $1
                    RETURNING owner_token
                    """,
                    job_id,
                    owner_token,
                    lease_seconds,
                )
                if not isinstance(claimed, UUID):
                    raise RuntimeError("database did not return the job owner token")
        return claimed

    async def heartbeat(
        self, job_id: UUID, owner_token: UUID, *, lease_seconds: int = 60
    ) -> datetime:
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int):
            raise ValueError("lease_seconds must be an integer")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        async with self._pool.acquire() as connection:
            expires_at = await connection.fetchval(
                """
                UPDATE ingestion_jobs
                SET lease_expires_at = now() + ($3 * interval '1 second')
                WHERE id = $1 AND owner_token = $2 AND status = 'running'
                  AND lease_expires_at > now()
                RETURNING lease_expires_at
                """,
                job_id,
                owner_token,
                lease_seconds,
            )
        if not isinstance(expires_at, datetime):
            raise JobStateError("job lease is stale or owned by another process")
        return expires_at

    async def start_attempt(
        self,
        job_id: UUID,
        owner_token: UUID,
        *,
        document_id: UUID,
        stage: str,
        configuration_id: str,
        input_fingerprint: str,
        retry_reason: str | None = None,
    ) -> StageAttempt:
        if not isinstance(stage, str) or not _STAGE_NAME.fullmatch(stage):
            raise ValueError("stage must be a lowercase identifier")
        _validate_identity(configuration_id, "configuration_id")
        _validate_identity(input_fingerprint, "input_fingerprint")
        if retry_reason is not None and (
            not isinstance(retry_reason, str) or not retry_reason.strip()
        ):
            raise ValueError("retry_reason must be a non-empty string or null")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                job = await connection.fetchrow(
                    """
                    SELECT status, owner_token, lease_expires_at,
                           lease_expires_at > now() AS lease_live
                    FROM ingestion_jobs WHERE id = $1 FOR UPDATE
                    """,
                    job_id,
                )
                if (
                    job is None
                    or job["status"] != "running"
                    or job["owner_token"] != owner_token
                    or not job["lease_live"]
                ):
                    raise JobStateError(
                        "stage attempt requires the current live job lease"
                    )
                attempt_number = await connection.fetchval(
                    """
                    SELECT COALESCE(max(attempt_number), 0) + 1
                    FROM ingestion_stage_attempts
                    WHERE job_id = $1 AND document_id = $2 AND stage = $3
                    """,
                    job_id,
                    document_id,
                    stage,
                )
                attempt_id = await connection.fetchval(
                    """
                    INSERT INTO ingestion_stage_attempts
                        (job_id, document_id, stage, attempt_number, status,
                         configuration_id, input_fingerprint, retry_reason, started_at)
                    VALUES ($1, $2, $3, $4, 'running', $5, $6, $7, now())
                    RETURNING id
                    """,
                    job_id,
                    document_id,
                    stage,
                    attempt_number,
                    configuration_id,
                    input_fingerprint,
                    retry_reason.strip() if retry_reason is not None else None,
                )
                await connection.execute(
                    """
                    INSERT INTO ingestion_documents (job_id, document_id, status, stage)
                    VALUES ($1, $2, 'running', $3)
                    ON CONFLICT (job_id, document_id)
                    DO UPDATE SET status = 'running', stage = EXCLUDED.stage,
                                  error_message = NULL, updated_at = now()
                    """,
                    job_id,
                    document_id,
                    stage,
                )
                started_at = await connection.fetchval(
                    "SELECT started_at FROM ingestion_stage_attempts WHERE id = $1",
                    attempt_id,
                )
        if not isinstance(attempt_id, UUID) or not isinstance(started_at, datetime):
            raise RuntimeError("database did not return a complete stage attempt")
        return StageAttempt(
            id=attempt_id,
            job_id=job_id,
            document_id=document_id,
            stage=stage,
            attempt_number=attempt_number,
            configuration_id=configuration_id,
            input_fingerprint=input_fingerprint,
            started_at=started_at,
            retry_reason=retry_reason.strip() if retry_reason is not None else None,
        )

    async def completed_output(
        self,
        job_id: UUID,
        document_id: UUID,
        *,
        stage: str,
        configuration_id: str,
        input_fingerprint: str,
    ) -> Mapping[str, object] | None:
        """Return a successful checkpoint only for identical effective inputs."""
        async with self._pool.acquire() as connection:
            serialized = await connection.fetchval(
                """
                SELECT output_references::text
                FROM ingestion_stage_attempts
                WHERE job_id = $1 AND document_id = $2 AND stage = $3
                  AND configuration_id = $4 AND input_fingerprint = $5
                  AND status = 'completed'
                ORDER BY attempt_number DESC
                LIMIT 1
                """,
                job_id,
                document_id,
                stage,
                configuration_id,
                input_fingerprint,
            )
        if serialized is None:
            return None
        output = json.loads(serialized)
        if not isinstance(output, dict):
            return None
        output_fingerprint = output.get("output_fingerprint")
        if not isinstance(output_fingerprint, str) or not _SHA256_ID.fullmatch(
            output_fingerprint
        ):
            return None
        return output

    async def finish_attempt(
        self,
        attempt_id: UUID,
        owner_token: UUID,
        *,
        status: AttemptStatus,
        output_references: Mapping[str, object] | None = None,
        failure_category: str | None = None,
        error_message: str | None = None,
        retryable: bool | None = None,
        resource_measurements: Mapping[str, object] | None = None,
    ) -> None:
        if status not in {"completed", "failed", "skipped"}:
            raise ValueError(
                "stage attempt status must be completed, failed or skipped"
            )
        if failure_category is not None and (
            not isinstance(failure_category, str)
            or not _FAILURE_CATEGORY.fullmatch(failure_category)
        ):
            raise ValueError("failure_category must be a machine-readable token")
        if status == "failed" and failure_category is None:
            raise ValueError("failed attempts require a failure category")
        safe_message = _safe_error_message(error_message)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT attempt.job_id, attempt.document_id, attempt.stage,
                           job.owner_token, job.status AS job_status,
                           job.lease_expires_at > now() AS lease_live
                    FROM ingestion_stage_attempts attempt
                    JOIN ingestion_jobs job ON job.id = attempt.job_id
                    WHERE attempt.id = $1 AND attempt.status = 'running'
                    FOR UPDATE OF attempt, job
                    """,
                    attempt_id,
                )
                if (
                    row is None
                    or row["owner_token"] != owner_token
                    or row["job_status"] != "running"
                    or not row["lease_live"]
                ):
                    raise JobStateError(
                        "stage attempt requires the current live job lease"
                    )
                await connection.execute(
                    """
                    UPDATE ingestion_stage_attempts
                    SET status = $2, output_references = $3::jsonb,
                        failure_category = $4, error_message = $5, retryable = $6,
                        completed_at = now(),
                        duration_ms = GREATEST(
                            0, floor(extract(epoch FROM (now() - started_at)) * 1000)
                        )::bigint,
                        resource_measurements = $7::jsonb
                    WHERE id = $1
                    """,
                    attempt_id,
                    status,
                    json.dumps(dict(output_references or {}), sort_keys=True),
                    failure_category,
                    safe_message,
                    retryable,
                    json.dumps(dict(resource_measurements or {}), sort_keys=True),
                )
                document_status = status
                await connection.execute(
                    """
                    UPDATE ingestion_documents
                    SET status = $3, error_message = $4, updated_at = now()
                    WHERE job_id = $1 AND document_id = $2
                    """,
                    row["job_id"],
                    row["document_id"],
                    document_status,
                    safe_message if status == "failed" else None,
                )

    async def finish_job(
        self,
        job_id: UUID,
        owner_token: UUID,
        *,
        status: Literal["completed", "failed", "cancelled"],
    ) -> None:
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("job must finish as completed, failed or cancelled")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                job = await connection.fetchrow(
                    """
                    SELECT status, owner_token, lease_expires_at > now() AS lease_live
                    FROM ingestion_jobs WHERE id = $1 FOR UPDATE
                    """,
                    job_id,
                )
                if (
                    job is None
                    or job["status"] != "running"
                    or job["owner_token"] != owner_token
                    or not job["lease_live"]
                ):
                    raise JobStateError(
                        "job lease is stale or owned by another process"
                    )
                running_attempts = await connection.fetchval(
                    """
                    SELECT count(*) FROM ingestion_stage_attempts
                    WHERE job_id = $1 AND status = 'running'
                    """,
                    job_id,
                )
                if running_attempts:
                    raise JobStateError(
                        "cannot finish a job with running stage attempts"
                    )
                if status == "completed":
                    incomplete_plan = await connection.fetchval(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM ingestion_job_plan plan
                            LEFT JOIN ingestion_documents document
                              ON document.job_id = plan.job_id
                             AND document.document_id = plan.document_id
                            WHERE plan.job_id = $1
                              AND (
                                  document.status IS DISTINCT FROM 'completed'
                                  OR NOT EXISTS (
                                      SELECT 1 FROM ingestion_stage_attempts attempt
                                      WHERE attempt.job_id = plan.job_id
                                        AND attempt.document_id = plan.document_id
                                        AND attempt.stage = plan.terminal_stage
                                        AND attempt.configuration_id =
                                            plan.terminal_configuration_id
                                        AND attempt.status = 'completed'
                                  )
                              )
                        )
                        """,
                        job_id,
                    )
                    if incomplete_plan:
                        raise JobStateError(
                            "cannot complete a job with unfinished planned documents"
                        )
                await connection.execute(
                    """
                    UPDATE ingestion_jobs
                    SET status = $2, completed_at = now(), owner_token = NULL,
                        lease_expires_at = NULL
                    WHERE id = $1
                    """,
                    job_id,
                    status,
                )

    async def get_summary(self, job_id: UUID) -> IngestionJobSummary:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT job.id, job.status, job.created_at, job.started_at,
                       job.completed_at, job.lease_expires_at,
                       (SELECT count(*) FROM ingestion_documents doc
                        WHERE doc.job_id = job.id) AS document_count,
                       (SELECT count(*) FROM ingestion_documents doc
                        WHERE doc.job_id = job.id AND doc.status = 'completed')
                           AS completed_documents,
                       (SELECT count(*) FROM ingestion_documents doc
                        WHERE doc.job_id = job.id AND doc.status = 'failed')
                           AS failed_documents,
                       (SELECT count(*) FROM ingestion_stage_attempts attempt
                        WHERE attempt.job_id = job.id AND attempt.status = 'running')
                           AS running_attempts,
                       (SELECT count(*) FROM ingestion_stage_attempts attempt
                        WHERE attempt.job_id = job.id AND attempt.status = 'failed')
                           AS failed_attempts
                FROM ingestion_jobs job WHERE job.id = $1
                """,
                job_id,
            )
        if row is None:
            raise JobStateError("ingestion job does not exist")
        return IngestionJobSummary(
            id=row["id"],
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            lease_expires_at=row["lease_expires_at"],
            document_count=row["document_count"],
            completed_documents=row["completed_documents"],
            failed_documents=row["failed_documents"],
            running_attempts=row["running_attempts"],
            failed_attempts=row["failed_attempts"],
        )


def _validate_identity(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_ID.fullmatch(value):
        raise ValueError(f"{name} must be a SHA-256 configuration identity")


def _safe_error_message(message: str | None) -> str | None:
    if message is None:
        return None
    if not isinstance(message, str):
        raise ValueError("error_message must be a string or null")
    if not message:
        return None
    # Parser and source adapters control exception text. It can contain paper
    # passages, credentials or URLs, so persist only the structured category.
    return _ERROR_DETAILS_OMITTED
