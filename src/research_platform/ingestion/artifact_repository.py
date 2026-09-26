"""Persist artifact checksums and source-specific permission evidence."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.acquisition import PermissionEvidence
from research_platform.ingestion.artifacts import (
    ArtifactStore,
    StoredArtifact,
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PermittedSourcePdf:
    association_id: UUID
    document_id: UUID
    sha256: str
    storage_path: str
    byte_size: int


@dataclass(frozen=True)
class UnreferencedArtifact:
    sha256: str
    storage_path: str
    byte_size: int
    created_at: datetime


@dataclass(frozen=True)
class ArtifactCleanupReport:
    removed_database_artifacts: tuple[str, ...]
    removed_unregistered_files: tuple[str, ...]
    removed_partial_files: tuple[str, ...]
    bytes_reclaimed: int


class ArtifactRepository:
    """Link an already published local artifact to one document version."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def permitted_source_pdf(
        self, document_id: UUID, *, require_indexing: bool = True
    ) -> PermittedSourcePdf:
        """Return the sole source PDF with matching persisted permission evidence."""
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT association.id AS association_id, association.document_id,
                       artifact.sha256, artifact.storage_path, artifact.byte_size
                FROM document_artifacts AS association
                JOIN artifacts AS artifact ON artifact.id = association.artifact_id
                JOIN document_permission_evidence AS permission
                  ON permission.id = association.permission_evidence_id
                 AND permission.document_id = association.document_id
                WHERE association.document_id = $1
                  AND association.role = 'source_pdf'
                  AND association.storage_permitted
                  AND permission.storage_permitted
                  AND ($2 = FALSE OR
                       (association.indexing_permitted AND permission.indexing_permitted))
                ORDER BY association.acquired_at DESC, association.id
                LIMIT 2
                """,
                document_id,
                require_indexing,
            )
        if not rows:
            raise PermissionError(
                "selected document has no source PDF with the required permission"
            )
        if len(rows) != 1:
            raise PermissionError(
                "selected document has multiple permitted source PDFs; choose one explicitly"
            )
        row = rows[0]
        if (
            not isinstance(row["association_id"], UUID)
            or row["document_id"] != document_id
            or not isinstance(row["sha256"], str)
            or not isinstance(row["storage_path"], str)
            or isinstance(row["byte_size"], bool)
            or not isinstance(row["byte_size"], int)
        ):
            raise RuntimeError("database returned an invalid permitted PDF record")
        return PermittedSourcePdf(
            association_id=row["association_id"],
            document_id=document_id,
            sha256=row["sha256"],
            storage_path=row["storage_path"],
            byte_size=row["byte_size"],
        )

    async def matching_permissioned_pdf(
        self,
        document_id: UUID,
        *,
        source_name: str,
        source_url: str,
        license_id: str,
    ) -> PermittedSourcePdf | None:
        """Find one already recorded PDF for the exact reviewed source route."""
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT association.id AS association_id, association.document_id,
                       artifact.sha256, artifact.storage_path, artifact.byte_size
                FROM document_artifacts AS association
                JOIN artifacts AS artifact ON artifact.id = association.artifact_id
                JOIN document_permission_evidence AS permission
                  ON permission.id = association.permission_evidence_id
                 AND permission.document_id = association.document_id
                WHERE association.document_id = $1
                  AND association.role = 'source_pdf'
                  AND association.source_name = $2
                  AND association.source_url = $3
                  AND permission.source_name = $2
                  AND permission.source_url = $3
                  AND permission.license_id = $4
                  AND association.storage_permitted
                  AND association.indexing_permitted
                  AND permission.storage_permitted
                  AND permission.indexing_permitted
                ORDER BY association.acquired_at DESC, association.id
                LIMIT 2
                """,
                document_id,
                source_name,
                source_url,
                license_id,
            )
        if len(rows) > 1:
            raise PermissionError(
                "selected document has multiple matching permitted source PDFs"
            )
        if not rows:
            return None
        row = rows[0]
        if (
            not isinstance(row["association_id"], UUID)
            or row["document_id"] != document_id
            or not isinstance(row["sha256"], str)
            or not isinstance(row["storage_path"], str)
            or isinstance(row["byte_size"], bool)
            or not isinstance(row["byte_size"], int)
        ):
            raise RuntimeError("database returned an invalid permitted PDF record")
        return PermittedSourcePdf(
            association_id=row["association_id"],
            document_id=document_id,
            sha256=row["sha256"],
            storage_path=row["storage_path"],
            byte_size=row["byte_size"],
        )

    async def known_storage_paths(self) -> set[str]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch("SELECT storage_path FROM artifacts")
        return {row["storage_path"] for row in rows}

    async def preview_unreferenced(
        self, *, created_before: datetime, limit: int = 100
    ) -> tuple[UnreferencedArtifact, ...]:
        """List old database artifacts with no document or retained snapshot link."""
        if created_before.tzinfo is None:
            raise ValueError("created_before must include a timezone")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT artifact.sha256, artifact.storage_path, artifact.byte_size,
                       artifact.created_at
                FROM artifacts artifact
                WHERE artifact.created_at < $1
                  AND NOT EXISTS (
                      SELECT 1 FROM document_artifacts association
                      WHERE association.artifact_id = artifact.id
                  )
                ORDER BY artifact.created_at, artifact.sha256
                LIMIT $2
                """,
                created_before,
                limit,
            )
        return tuple(
            UnreferencedArtifact(
                sha256=row["sha256"],
                storage_path=row["storage_path"],
                byte_size=row["byte_size"],
                created_at=row["created_at"],
            )
            for row in rows
        )

    async def cleanup_unreferenced(
        self,
        store: ArtifactStore,
        *,
        created_before: datetime,
        limit: int = 100,
    ) -> ArtifactCleanupReport:
        """Retire only old orphaned files while no ingestion job can be writing."""
        if created_before.tzinfo is None:
            raise ValueError("created_before must include a timezone")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                lock_acquired = await connection.fetchval(
                    "SELECT pg_try_advisory_xact_lock(60201, 1)"
                )
                if not lock_acquired:
                    raise RuntimeError(
                        "another process is changing ingestion ownership"
                    )
                active_job = await connection.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM ingestion_jobs WHERE status = 'running')"
                )
                if active_job:
                    raise RuntimeError(
                        "artifact cleanup is blocked while an ingestion job is running"
                    )
                known_paths = {
                    row["storage_path"]
                    for row in await connection.fetch(
                        "SELECT storage_path FROM artifacts"
                    )
                }
                rows = await connection.fetch(
                    """
                    SELECT artifact.id, artifact.sha256, artifact.storage_path,
                           artifact.byte_size
                    FROM artifacts artifact
                    WHERE artifact.created_at < $1
                      AND NOT EXISTS (
                          SELECT 1 FROM document_artifacts association
                          WHERE association.artifact_id = artifact.id
                      )
                    ORDER BY artifact.created_at, artifact.sha256
                    LIMIT $2
                    FOR UPDATE OF artifact SKIP LOCKED
                    """,
                    created_before,
                    limit,
                )
                unregistered = (
                    await asyncio.to_thread(
                        store.stale_unregistered_files,
                        known_paths,
                        created_before=created_before,
                    )
                )[:limit]
                partials = (
                    await asyncio.to_thread(
                        store.stale_partial_files, created_before=created_before
                    )
                )[:limit]
                removed_database: list[str] = []
                removed_unregistered: list[str] = []
                removed_partials: list[str] = []
                bytes_reclaimed = 0
                for row in rows:
                    deleted = await connection.execute(
                        """
                        DELETE FROM artifacts
                        WHERE id = $1 AND NOT EXISTS (
                            SELECT 1 FROM document_artifacts association
                            WHERE association.artifact_id = $1
                        )
                        """,
                        row["id"],
                    )
                    if deleted != "DELETE 1":
                        raise RuntimeError("artifact became referenced during cleanup")
                    bytes_reclaimed += await asyncio.to_thread(
                        store.remove_content_addressed_pdf,
                        sha256=row["sha256"],
                        storage_path=row["storage_path"],
                        expected_byte_size=row["byte_size"],
                    )
                    removed_database.append(row["sha256"])
                for candidate in unregistered:
                    bytes_reclaimed += await asyncio.to_thread(
                        store.remove_unregistered_pdf,
                        candidate,
                        created_before=created_before,
                    )
                    removed_unregistered.append(candidate.storage_path)
                for candidate in partials:
                    bytes_reclaimed += await asyncio.to_thread(
                        store.remove_stale_partial,
                        candidate,
                        created_before=created_before,
                    )
                    removed_partials.append(candidate.storage_path)
        return ArtifactCleanupReport(
            removed_database_artifacts=tuple(removed_database),
            removed_unregistered_files=tuple(removed_unregistered),
            removed_partial_files=tuple(removed_partials),
            bytes_reclaimed=bytes_reclaimed,
        )

    async def record_download(
        self,
        document_id: UUID,
        artifact: StoredArtifact,
        permission: PermissionEvidence,
        *,
        acquired_at: datetime | None = None,
    ) -> UUID:
        """Persist the checksum and the review decision that allowed acquisition."""
        if not _SHA256_PATTERN.fullmatch(artifact.sha256):
            raise ValueError("artifact SHA-256 must be lowercase hexadecimal")
        relative_path = PurePosixPath(artifact.storage_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("artifact storage path must be a safe relative path")
        if artifact.byte_size <= 0 or artifact.media_type != "application/pdf":
            raise ValueError("download record must reference a non-empty PDF artifact")
        acquired_at = acquired_at or datetime.now(timezone.utc)
        if acquired_at.tzinfo is None:
            acquired_at = acquired_at.replace(tzinfo=timezone.utc)

        evidence_metadata = {
            "license_id": permission.license_id,
            "terms_url": permission.terms_url,
            "reviewer": permission.reviewer,
            "rights_checked_at": permission.checked_at.isoformat(),
        }
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                permission_evidence_id = await connection.fetchval(
                    """
                    INSERT INTO document_permission_evidence
                        (document_id, source_name, source_url, license_id, terms_url,
                         permission_basis, reviewer, checked_at, storage_permitted,
                         indexing_permitted, passage_display_permitted)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT
                        (document_id, source_name, source_url, license_id, checked_at, reviewer)
                    DO NOTHING
                    RETURNING id
                    """,
                    document_id,
                    permission.source_name,
                    permission.source_url,
                    permission.license_id,
                    permission.terms_url,
                    permission.basis,
                    permission.reviewer,
                    permission.checked_at,
                    permission.storage_permitted,
                    permission.indexing_permitted,
                    permission.passage_display_permitted,
                )
                evidence = await connection.fetchrow(
                    """
                    SELECT id, terms_url, permission_basis, storage_permitted,
                           indexing_permitted, passage_display_permitted
                    FROM document_permission_evidence
                    WHERE document_id = $1 AND source_name = $2 AND source_url = $3
                      AND license_id = $4 AND checked_at = $5 AND reviewer = $6
                    FOR SHARE
                    """,
                    document_id,
                    permission.source_name,
                    permission.source_url,
                    permission.license_id,
                    permission.checked_at,
                    permission.reviewer,
                )
                if evidence is None:
                    raise RuntimeError(
                        "permission evidence was not visible in its transaction"
                    )
                if (
                    evidence["terms_url"] != permission.terms_url
                    or evidence["permission_basis"] != permission.basis
                    or evidence["storage_permitted"] != permission.storage_permitted
                    or evidence["indexing_permitted"] != permission.indexing_permitted
                    or evidence["passage_display_permitted"]
                    != permission.passage_display_permitted
                ):
                    raise ValueError(
                        "permission evidence conflicts with a prior review"
                    )
                if permission_evidence_id is None:
                    permission_evidence_id = evidence["id"]

                artifact_id = await connection.fetchval(
                    """
                    INSERT INTO artifacts (sha256, storage_path, byte_size, media_type)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (sha256) DO NOTHING
                    RETURNING id
                    """,
                    artifact.sha256,
                    relative_path.as_posix(),
                    artifact.byte_size,
                    artifact.media_type,
                )
                existing = await connection.fetchrow(
                    """
                    SELECT id, storage_path, byte_size, media_type
                    FROM artifacts WHERE sha256 = $1 FOR SHARE
                    """,
                    artifact.sha256,
                )
                if existing is None:
                    raise RuntimeError(
                        "artifact insert was not visible in its transaction"
                    )
                if (
                    existing["storage_path"] != relative_path.as_posix()
                    or existing["byte_size"] != artifact.byte_size
                    or existing["media_type"] != artifact.media_type
                ):
                    raise ValueError(
                        "stored artifact metadata conflicts with its checksum"
                    )
                if artifact_id is None:
                    artifact_id = existing["id"]
                association_id = await connection.fetchval(
                    """
                    INSERT INTO document_artifacts
                        (document_id, artifact_id, role, source_name, source_url,
                         acquired_at, permission_basis, storage_permitted,
                         indexing_permitted, passage_display_permitted, metadata,
                         permission_evidence_id)
                    VALUES ($1, $2, 'source_pdf', $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
                    ON CONFLICT (document_id, artifact_id, role, source_url)
                    DO UPDATE SET acquired_at = EXCLUDED.acquired_at,
                                  permission_basis = EXCLUDED.permission_basis,
                                  storage_permitted = EXCLUDED.storage_permitted,
                                  indexing_permitted = EXCLUDED.indexing_permitted,
                                  passage_display_permitted = EXCLUDED.passage_display_permitted,
                                  metadata = EXCLUDED.metadata,
                                  permission_evidence_id = EXCLUDED.permission_evidence_id
                    RETURNING id
                    """,
                    document_id,
                    artifact_id,
                    permission.source_name,
                    permission.source_url,
                    acquired_at,
                    permission.basis,
                    permission.storage_permitted,
                    permission.indexing_permitted,
                    permission.passage_display_permitted,
                    json.dumps(evidence_metadata, sort_keys=True),
                    permission_evidence_id,
                )
                updated_document = await connection.execute(
                    "UPDATE documents SET status = 'acquired' WHERE id = $1",
                    document_id,
                )
                if updated_document != "UPDATE 1":
                    raise RuntimeError("downloaded artifact document was not updated")
        if not isinstance(association_id, UUID):
            raise RuntimeError("database did not return a document artifact ID")
        return association_id
