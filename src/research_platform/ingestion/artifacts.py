"""Bounded, content-addressed local storage for acquired PDF artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


class ArtifactError(RuntimeError):
    """An artifact could not be safely validated or stored."""


class ArtifactLimitExceeded(ArtifactError):
    """An artifact or the configured store would exceed its byte limit."""


@dataclass(frozen=True)
class StoredArtifact:
    sha256: str
    storage_path: str
    byte_size: int
    media_type: str = "application/pdf"


@dataclass(frozen=True)
class StorageInspection:
    stored_bytes: int
    store_limit_bytes: int
    remaining_store_bytes: int
    filesystem_free_bytes: int
    partial_file_count: int
    partial_bytes: int


def resolve_registered_pdf(
    root: Path, storage_path: str, *, sha256: str, byte_size: int
) -> Path:
    """Verify a registered content-addressed PDF before opening it for parsing."""
    resolved_root = root.expanduser().resolve()
    relative_path = PurePosixPath(storage_path)
    expected_path = PurePosixPath("sha256") / sha256[:2] / f"{sha256}.pdf"
    if (
        not re.fullmatch(r"[0-9a-f]{64}", sha256)
        or relative_path != expected_path
        or relative_path.is_absolute()
        or ".." in relative_path.parts
    ):
        raise ArtifactError("registered PDF path or checksum is invalid")
    candidate = resolved_root.joinpath(*relative_path.parts)
    if any(
        component.is_symlink()
        for component in (candidate, *candidate.parents)
        if component == resolved_root or component.is_relative_to(resolved_root)
    ):
        raise ArtifactError("registered PDF path cannot contain symlinks")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise ArtifactError("registered PDF file is missing") from None
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise ArtifactError("registered PDF path is not a regular in-store file")
    actual_sha256, actual_size = _file_digest_and_size(resolved)
    if actual_sha256 != sha256 or actual_size != byte_size:
        raise ArtifactError("registered PDF checksum or byte size changed")
    return resolved


@dataclass(frozen=True)
class CleanupFileCandidate:
    storage_path: str
    byte_size: int
    modified_at: datetime
    sha256: str | None


class ArtifactStore:
    """Write complete PDFs atomically under a storage root outside Git."""

    def __init__(
        self,
        root: Path,
        *,
        maximum_file_bytes: int,
        maximum_store_bytes: int,
    ) -> None:
        if maximum_file_bytes <= 0 or maximum_store_bytes <= 0:
            raise ValueError("artifact storage limits must be positive")
        if maximum_file_bytes > maximum_store_bytes:
            raise ValueError("maximum_file_bytes cannot exceed maximum_store_bytes")
        self.root = root.expanduser().resolve()
        self.maximum_file_bytes = maximum_file_bytes
        self.maximum_store_bytes = maximum_store_bytes
        self._write_lock = asyncio.Lock()

    async def store_pdf(
        self,
        chunks: AsyncIterable[bytes],
        *,
        declared_length: int | None = None,
    ) -> StoredArtifact:
        """Serialize this store's writers so concurrent streams cannot exceed its cap."""
        async with self._write_lock:
            return await self._store_pdf(chunks, declared_length=declared_length)

    async def _store_pdf(
        self,
        chunks: AsyncIterable[bytes],
        *,
        declared_length: int | None = None,
    ) -> StoredArtifact:
        """Stream, validate, hash and atomically publish one PDF."""
        if declared_length is not None and declared_length < 0:
            raise ArtifactError("content length cannot be negative")
        if declared_length is not None and declared_length > self.maximum_file_bytes:
            raise ArtifactLimitExceeded("PDF exceeds the per-file size limit")

        self.root.mkdir(parents=True, exist_ok=True)
        stored_bytes = await asyncio.to_thread(self._stored_bytes)
        if stored_bytes >= self.maximum_store_bytes:
            raise ArtifactLimitExceeded("artifact store has reached its size limit")

        temporary_path: Path | None = None
        digest = hashlib.sha256()
        byte_size = 0
        header = bytearray()
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.root, prefix=".partial-", delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                async for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise ArtifactError("download stream yielded non-byte data")
                    if not chunk:
                        continue
                    byte_size += len(chunk)
                    if byte_size > self.maximum_file_bytes:
                        raise ArtifactLimitExceeded(
                            "PDF exceeds the per-file size limit"
                        )
                    if stored_bytes + byte_size > self.maximum_store_bytes:
                        raise ArtifactLimitExceeded(
                            "artifact store size limit exceeded"
                        )
                    if len(header) < 8:
                        header.extend(chunk[: 8 - len(header)])
                    digest.update(chunk)
                    temporary_file.write(chunk)
                if not header.startswith(b"%PDF-"):
                    raise ArtifactError("downloaded content does not have a PDF header")
                if declared_length is not None and byte_size != declared_length:
                    raise ArtifactError(
                        "downloaded PDF length does not match the response"
                    )
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            checksum = digest.hexdigest()
            relative_path = Path("sha256") / checksum[:2] / f"{checksum}.pdf"
            destination = self.root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                existing_digest, existing_size = await asyncio.to_thread(
                    _file_digest_and_size, destination
                )
                if existing_digest != checksum or existing_size != byte_size:
                    raise ArtifactError(
                        "existing content-addressed artifact is corrupt"
                    )
                temporary_path.unlink(missing_ok=True)
            else:
                os.replace(temporary_path, destination)
            temporary_path = None
            return StoredArtifact(
                sha256=checksum,
                storage_path=relative_path.as_posix(),
                byte_size=byte_size,
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def resolve_registered_pdf(
        self, storage_path: str, *, sha256: str, byte_size: int
    ) -> Path:
        """Verify a registered content-addressed PDF before opening it for parsing."""
        relative_path = PurePosixPath(storage_path)
        expected_path = PurePosixPath("sha256") / sha256[:2] / f"{sha256}.pdf"
        if (
            not re.fullmatch(r"[0-9a-f]{64}", sha256)
            or relative_path != expected_path
            or relative_path.is_absolute()
            or ".." in relative_path.parts
        ):
            raise ArtifactError("registered PDF path or checksum is invalid")
        candidate = self.root.joinpath(*relative_path.parts)
        if any(
            component.is_symlink()
            for component in (candidate, *candidate.parents)
            if component != self.root.parent and component.is_relative_to(self.root)
        ):
            raise ArtifactError("registered PDF path cannot contain symlinks")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            raise ArtifactError("registered PDF file is missing") from None
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ArtifactError("registered PDF path is not a regular in-store file")
        actual_sha256, actual_size = _file_digest_and_size(resolved)
        if actual_sha256 != sha256 or actual_size != byte_size:
            raise ArtifactError("registered PDF checksum or byte size changed")
        return resolved

    def inspect(self) -> StorageInspection:
        """Report artifact bytes, temporary files and free filesystem capacity."""
        stored_bytes = self._stored_bytes()
        partial_files = tuple(
            path
            for path in self.root.glob(".partial-*")
            if path.is_file() and not path.is_symlink()
        )
        partial_bytes = sum(path.stat().st_size for path in partial_files)
        filesystem_root = self.root
        while (
            not filesystem_root.exists() and filesystem_root != filesystem_root.parent
        ):
            filesystem_root = filesystem_root.parent
        free_bytes = shutil.disk_usage(filesystem_root).free
        return StorageInspection(
            stored_bytes=stored_bytes,
            store_limit_bytes=self.maximum_store_bytes,
            remaining_store_bytes=max(0, self.maximum_store_bytes - stored_bytes),
            filesystem_free_bytes=free_bytes,
            partial_file_count=len(partial_files),
            partial_bytes=partial_bytes,
        )

    def unregistered_files(self, known_storage_paths: set[str]) -> tuple[str, ...]:
        """List content-addressed files missing a PostgreSQL artifact record."""
        artifact_root = self.root / "sha256"
        if not artifact_root.exists():
            return ()
        return tuple(
            sorted(
                path.relative_to(self.root).as_posix()
                for path in artifact_root.rglob("*.pdf")
                if path.is_file()
                and not path.is_symlink()
                and path.relative_to(self.root).as_posix() not in known_storage_paths
            )
        )

    def stale_unregistered_files(
        self, known_storage_paths: set[str], *, created_before: datetime
    ) -> tuple[CleanupFileCandidate, ...]:
        """Find old, checksum-addressed PDFs that have no database record."""
        cutoff = _utc_cutoff(created_before)
        artifact_root = self.root / "sha256"
        if not artifact_root.exists():
            return ()
        candidates: list[CleanupFileCandidate] = []
        for path in artifact_root.rglob("*.pdf"):
            if not path.is_file() or path.is_symlink():
                continue
            storage_path = path.relative_to(self.root).as_posix()
            if storage_path in known_storage_paths:
                continue
            sha256 = _checksum_from_storage_path(storage_path)
            if sha256 is None:
                continue
            stat = path.stat()
            modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            if modified_at < cutoff:
                candidates.append(
                    CleanupFileCandidate(
                        storage_path, stat.st_size, modified_at, sha256
                    )
                )
        return tuple(sorted(candidates, key=lambda item: item.storage_path))

    def stale_partial_files(
        self, *, created_before: datetime
    ) -> tuple[CleanupFileCandidate, ...]:
        """Find old interrupted writes at the artifact root, excluding symlinks."""
        cutoff = _utc_cutoff(created_before)
        if not self.root.exists():
            return ()
        candidates: list[CleanupFileCandidate] = []
        for path in self.root.glob(".partial-*"):
            if not path.is_file() or path.is_symlink():
                continue
            stat = path.stat()
            modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            if modified_at < cutoff:
                candidates.append(
                    CleanupFileCandidate(
                        path.relative_to(self.root).as_posix(),
                        stat.st_size,
                        modified_at,
                        None,
                    )
                )
        return tuple(sorted(candidates, key=lambda item: item.storage_path))

    def remove_content_addressed_pdf(
        self,
        *,
        sha256: str,
        storage_path: str,
        expected_byte_size: int | None = None,
        created_before: datetime | None = None,
    ) -> int:
        """Remove one verified generated PDF; missing files are safe to retry."""
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ArtifactError("artifact SHA-256 is invalid")
        expected_path = PurePosixPath("sha256", sha256[:2], f"{sha256}.pdf")
        if storage_path != expected_path.as_posix():
            raise ArtifactError("artifact path does not match its SHA-256")
        target = self.root.joinpath(*expected_path.parts)
        root = self.root.resolve()
        if not target.parent.resolve().is_relative_to(root):
            raise ArtifactError("artifact path resolves outside the storage root")
        if target.is_symlink():
            raise ArtifactError("refusing to remove a symbolic link as an artifact")
        if not target.exists():
            return 0
        if not target.is_file():
            raise ArtifactError("artifact path is not a regular file")
        stat = target.stat()
        if created_before is not None:
            cutoff = _utc_cutoff(created_before)
            modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            if modified_at >= cutoff:
                raise ArtifactError("artifact file is newer than the cleanup cutoff")
        digest, byte_size = _file_digest_and_size(target)
        if digest != sha256:
            raise ArtifactError(
                "artifact bytes do not match their content-addressed path"
            )
        if expected_byte_size is not None and byte_size != expected_byte_size:
            raise ArtifactError("artifact byte size differs from its database record")
        target.unlink()
        for directory in (target.parent, target.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                pass
        return byte_size

    def remove_stale_partial(
        self, candidate: CleanupFileCandidate, *, created_before: datetime
    ) -> int:
        """Remove one previewed partial file after rechecking its path and age."""
        if (
            candidate.sha256 is not None
            or PurePosixPath(candidate.storage_path).parent != PurePosixPath(".")
            or not Path(candidate.storage_path).name.startswith(".partial-")
        ):
            raise ArtifactError("cleanup candidate is not a root-level partial file")
        target = self.root / candidate.storage_path
        if target.is_symlink():
            raise ArtifactError("refusing to remove a symbolic link as a partial file")
        if not target.exists():
            return 0
        if not target.is_file():
            raise ArtifactError("partial path is not a regular file")
        stat = target.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        if modified_at >= _utc_cutoff(created_before):
            raise ArtifactError("partial file is newer than the cleanup cutoff")
        if stat.st_size != candidate.byte_size:
            raise ArtifactError("partial file changed after cleanup inspection")
        target.unlink()
        return stat.st_size

    def remove_unregistered_pdf(
        self, candidate: CleanupFileCandidate, *, created_before: datetime
    ) -> int:
        """Remove one old unregistered PDF after rechecking checksum and age."""
        if candidate.sha256 is None:
            raise ArtifactError("cleanup candidate is not a content-addressed PDF")
        return self.remove_content_addressed_pdf(
            sha256=candidate.sha256,
            storage_path=candidate.storage_path,
            expected_byte_size=candidate.byte_size,
            created_before=created_before,
        )

    def _stored_bytes(self) -> int:
        artifact_root = self.root / "sha256"
        if not artifact_root.exists():
            return 0
        return sum(
            item.stat().st_size
            for item in artifact_root.rglob("*")
            if item.is_file() and not item.is_symlink()
        )


def _file_digest_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as artifact_file:
        for chunk in iter(lambda: artifact_file.read(1024 * 1024), b""):
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def _utc_cutoff(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("cleanup cutoff must include a timezone")
    return value.astimezone(timezone.utc)


def _checksum_from_storage_path(storage_path: str) -> str | None:
    path = PurePosixPath(storage_path)
    if len(path.parts) != 3 or path.parts[0] != "sha256":
        return None
    filename = path.name
    if not filename.endswith(".pdf"):
        return None
    sha256 = filename.removesuffix(".pdf")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256) or path.parts[1] != sha256[:2]:
        return None
    return sha256
