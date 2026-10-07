"""Persist reproducible evaluation experiment records and private item results."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

MetricValue = float | int | None


class ExperimentStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExperimentNotFound(LookupError):
    """No experiment has the requested ID."""


@dataclass(frozen=True)
class DatasetIdentity:
    name: str
    version: str
    sha256: str


@dataclass(frozen=True)
class ExperimentOutcome:
    configuration_id: str | None
    configuration: dict[str, object]
    versions: dict[str, str]
    random_seed: int | None
    metrics: dict[str, MetricValue]
    failures: dict[str, int]
    item_count: int


class ExperimentRecord(BaseModel):
    """One evaluation run and its §13.3 provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: UUID
    suite: str
    status: ExperimentStatus
    dataset_name: str
    dataset_version: str
    dataset_sha256: str
    code_revision: str
    configuration_id: str | None = None
    configuration: dict[str, object] = Field(default_factory=dict)
    versions: dict[str, str] = Field(default_factory=dict)
    random_seed: int | None = None
    hardware: dict[str, object] = Field(default_factory=dict)
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    failures: dict[str, int] = Field(default_factory=dict)
    items_path: str
    item_count: int = Field(0, ge=0)
    notes: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


class ExperimentStore(Protocol):
    async def start(self, record: ExperimentRecord) -> None: ...

    async def finish(
        self,
        experiment_id: UUID,
        *,
        status: ExperimentStatus,
        outcome: ExperimentOutcome,
    ) -> ExperimentRecord: ...

    async def get(self, experiment_id: UUID) -> ExperimentRecord: ...

    async def list(
        self, *, suite: str | None = None, limit: int = 50
    ) -> tuple[ExperimentRecord, ...]: ...


class PostgresExperimentStore:
    """Asyncpg adapter for experiment records."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def start(self, record: ExperimentRecord) -> None:
        if record.status is not ExperimentStatus.RUNNING:
            raise ValueError("an experiment must start in running status")
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO experiments (
                    experiment_id, suite, status, dataset_name, dataset_version,
                    dataset_sha256, code_revision, configuration_id, configuration,
                    versions, random_seed, hardware, metrics, failures, items_path,
                    item_count, notes, started_at, completed_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb,
                    $11, $12::jsonb, $13::jsonb, $14::jsonb, $15, $16, $17, $18, $19
                )
                """,
                record.experiment_id,
                record.suite,
                record.status.value,
                record.dataset_name,
                record.dataset_version,
                record.dataset_sha256,
                record.code_revision,
                record.configuration_id,
                json.dumps(record.configuration),
                json.dumps(record.versions),
                record.random_seed,
                json.dumps(record.hardware),
                json.dumps(record.metrics),
                json.dumps(record.failures),
                record.items_path,
                record.item_count,
                record.notes,
                record.started_at,
                record.completed_at,
            )

    async def finish(
        self,
        experiment_id: UUID,
        *,
        status: ExperimentStatus,
        outcome: ExperimentOutcome,
    ) -> ExperimentRecord:
        if status is ExperimentStatus.RUNNING:
            raise ValueError("finished status must be completed or failed")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                current = await connection.fetchrow(
                    "SELECT status FROM experiments WHERE experiment_id = $1 FOR UPDATE",
                    experiment_id,
                )
                if current is None:
                    raise ExperimentNotFound(str(experiment_id))
                if current["status"] != ExperimentStatus.RUNNING.value:
                    raise ValueError("only a running experiment can be finished")
                row = await connection.fetchrow(
                    """
                    UPDATE experiments
                    SET status = $2, configuration_id = $3,
                        configuration = $4::jsonb, versions = $5::jsonb,
                        random_seed = $6, metrics = $7::jsonb, failures = $8::jsonb,
                        item_count = $9, completed_at = now()
                    WHERE experiment_id = $1
                    RETURNING *
                    """,
                    experiment_id,
                    status.value,
                    outcome.configuration_id,
                    json.dumps(outcome.configuration),
                    json.dumps(outcome.versions),
                    outcome.random_seed,
                    json.dumps(outcome.metrics),
                    json.dumps(outcome.failures),
                    outcome.item_count,
                )
        if row is None:
            raise ExperimentNotFound(str(experiment_id))
        return _record_from_row(row)

    async def get(self, experiment_id: UUID) -> ExperimentRecord:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM experiments WHERE experiment_id = $1", experiment_id
            )
        if row is None:
            raise ExperimentNotFound(str(experiment_id))
        return _record_from_row(row)

    async def list(
        self, *, suite: str | None = None, limit: int = 50
    ) -> tuple[ExperimentRecord, ...]:
        _validate_limit(limit)
        async with self._pool.acquire() as connection:
            if suite is None:
                rows = await connection.fetch(
                    """
                    SELECT * FROM experiments
                    ORDER BY started_at DESC, experiment_id DESC LIMIT $1
                    """,
                    limit,
                )
            else:
                rows = await connection.fetch(
                    """
                    SELECT * FROM experiments WHERE suite = $1
                    ORDER BY started_at DESC, experiment_id DESC LIMIT $2
                    """,
                    suite,
                    limit,
                )
        return tuple(_record_from_row(row) for row in rows)


class InMemoryExperimentStore:
    """Dictionary-backed experiment store with the PostgreSQL lifecycle."""

    def __init__(self) -> None:
        self._records: dict[UUID, ExperimentRecord] = {}

    async def start(self, record: ExperimentRecord) -> None:
        if record.status is not ExperimentStatus.RUNNING:
            raise ValueError("an experiment must start in running status")
        if record.experiment_id in self._records:
            raise ValueError("experiment already exists")
        self._records[record.experiment_id] = record

    async def finish(
        self,
        experiment_id: UUID,
        *,
        status: ExperimentStatus,
        outcome: ExperimentOutcome,
    ) -> ExperimentRecord:
        if status is ExperimentStatus.RUNNING:
            raise ValueError("finished status must be completed or failed")
        record = await self.get(experiment_id)
        if record.status is not ExperimentStatus.RUNNING:
            raise ValueError("only a running experiment can be finished")
        updated = record.model_copy(
            update={
                "status": status,
                "configuration_id": outcome.configuration_id,
                "configuration": outcome.configuration,
                "versions": outcome.versions,
                "random_seed": outcome.random_seed,
                "metrics": outcome.metrics,
                "failures": outcome.failures,
                "item_count": outcome.item_count,
                "completed_at": datetime.now(UTC),
            }
        )
        self._records[experiment_id] = updated
        return updated

    async def get(self, experiment_id: UUID) -> ExperimentRecord:
        try:
            return self._records[experiment_id]
        except KeyError:
            raise ExperimentNotFound(str(experiment_id)) from None

    async def list(
        self, *, suite: str | None = None, limit: int = 50
    ) -> tuple[ExperimentRecord, ...]:
        _validate_limit(limit)
        records = sorted(
            (
                record
                for record in self._records.values()
                if suite is None or record.suite == suite
            ),
            key=lambda record: (record.started_at, record.experiment_id),
            reverse=True,
        )
        return tuple(records[:limit])


def canonical_repository_root() -> Path:
    """Resolve private-data paths through the repository's shared Git metadata."""
    checkout = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        raise RuntimeError("could not resolve the canonical Git checkout") from None
    common_dir = Path(result.stdout.strip()).resolve()
    root = common_dir.parent if common_dir.name == ".git" else checkout
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if root == temporary_root or root.is_relative_to(temporary_root):
        raise RuntimeError(
            "private experiment data cannot be rooted in a temporary checkout"
        )
    return root


def default_experiments_root() -> Path:
    return canonical_repository_root() / "local-reference/experiments"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hardware_profile() -> dict[str, object]:
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="ascii")
        memory = next(
            line for line in meminfo.splitlines() if line.startswith("MemTotal:")
        )
        mem_total_mib: int | None = int(memory.split()[1]) // 1024
    except (OSError, StopIteration, ValueError, IndexError):
        mem_total_mib = None
    try:
        gpu = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        gpu = None
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "mem_total_mib": mem_total_mib,
        "gpu": gpu,
    }


class ExperimentItemWriter:
    """Appends private per-item results for one experiment."""

    def __init__(self, experiment_id: UUID, *, root: Path | None = None) -> None:
        self._directory = (root or default_experiments_root()) / str(experiment_id)
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._directory, stat.S_IRWXU)
        self._path = self._directory / "items.jsonl"
        self._count = len(read_items(self._path)) if self._path.exists() else 0

    @property
    def path(self) -> Path:
        return self._path

    def append(self, item: Mapping[str, object]) -> None:
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("item must have a non-empty string item_id")
        encoded = (json.dumps(item, sort_keys=True, default=str) + "\n").encode()
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            with os.fdopen(descriptor, "ab") as target:
                target.write(encoded)
                target.flush()
                os.fsync(target.fileno())
        except Exception:
            raise
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        self._count += 1

    @property
    def count(self) -> int:
        return self._count


def read_items(path: Path) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("experiment item must be a JSON object")
                items.append(item)
    return items


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")


def _record_from_row(row: asyncpg.Record) -> ExperimentRecord:
    values = dict(row)
    for key in ("configuration", "versions", "hardware", "metrics", "failures"):
        if isinstance(values[key], str):
            values[key] = json.loads(values[key])
    return ExperimentRecord.model_validate(values)
