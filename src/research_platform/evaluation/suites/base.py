"""Shared interfaces and lifecycle for evaluation suites."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from research_platform.config import Settings
from research_platform.evaluation.experiments import (
    DatasetIdentity,
    ExperimentItemWriter,
    ExperimentOutcome,
    ExperimentRecord,
    ExperimentStatus,
    ExperimentStore,
    hardware_profile,
)
from research_platform.ingestion.provenance import code_revision


@dataclass(frozen=True)
class SuiteContext:
    experiment_id: UUID
    writer: ExperimentItemWriter
    settings: Settings
    options: Mapping[str, str]


class Suite(Protocol):
    name: str

    def dataset(self, options: Mapping[str, str]) -> DatasetIdentity: ...

    async def run(self, context: SuiteContext) -> ExperimentOutcome: ...


async def run_suite(
    suite: Suite,
    *,
    store: ExperimentStore,
    settings: Settings,
    options: Mapping[str, str],
    notes: str | None = None,
    items_root: Path | None = None,
) -> ExperimentRecord:
    """Run a suite and persist its experiment lifecycle."""
    experiment_id = uuid4()
    dataset = suite.dataset(options)
    writer = ExperimentItemWriter(experiment_id, root=items_root)
    await store.start(
        ExperimentRecord(
            experiment_id=experiment_id,
            suite=suite.name,
            status=ExperimentStatus.RUNNING,
            dataset_name=dataset.name,
            dataset_version=dataset.version,
            dataset_sha256=dataset.sha256,
            code_revision=code_revision(),
            hardware=hardware_profile(),
            items_path=str(writer.path),
            item_count=writer.count,
            started_at=datetime.now(UTC),
            notes=notes,
        )
    )
    try:
        outcome = await suite.run(
            SuiteContext(
                experiment_id=experiment_id,
                writer=writer,
                settings=settings,
                options=options,
            )
        )
    except Exception as error:
        await store.finish(
            experiment_id,
            status=ExperimentStatus.FAILED,
            outcome=ExperimentOutcome(
                None, {}, {}, None, {}, {type(error).__name__: 1}, writer.count
            ),
        )
        raise
    return await store.finish(
        experiment_id, status=ExperimentStatus.COMPLETED, outcome=outcome
    )
