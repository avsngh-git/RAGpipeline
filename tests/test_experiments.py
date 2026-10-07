"""Unit coverage for experiment persistence and private item files."""

from __future__ import annotations

import hashlib
import stat
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from research_platform.evaluation.experiments import (
    DatasetIdentity,
    ExperimentItemWriter,
    ExperimentNotFound,
    ExperimentOutcome,
    ExperimentRecord,
    ExperimentStatus,
    InMemoryExperimentStore,
    file_sha256,
    hardware_profile,
    read_items,
)


def _record(suite: str = "agent-dev", *, age: int = 0) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=uuid4(),
        suite=suite,
        status=ExperimentStatus.RUNNING,
        dataset_name="fixture",
        dataset_version="v1",
        dataset_sha256="a" * 64,
        code_revision="revision",
        items_path="private/items.jsonl",
        started_at=datetime.now(UTC) - timedelta(seconds=age),
    )


def _outcome(*, item_count: int = 2) -> ExperimentOutcome:
    return ExperimentOutcome(
        configuration_id="config-v1",
        configuration={"mode": "quick"},
        versions={"generator": "scripted"},
        random_seed=7,
        metrics={"score": 0.75, "items": item_count},
        failures={"timeout": 1},
        item_count=item_count,
    )


@pytest.mark.anyio
async def test_in_memory_store_lifecycle() -> None:
    store = InMemoryExperimentStore()
    record = _record()
    await store.start(record)

    running = await store.get(record.experiment_id)
    completed = await store.finish(
        record.experiment_id,
        status=ExperimentStatus.COMPLETED,
        outcome=_outcome(),
    )
    loaded = await store.get(record.experiment_id)

    assert running.status is ExperimentStatus.RUNNING
    assert completed == loaded
    assert loaded.status is ExperimentStatus.COMPLETED
    assert loaded.completed_at is not None
    assert loaded.metrics == {"score": 0.75, "items": 2}


@pytest.mark.anyio
async def test_finish_twice_rejected() -> None:
    store = InMemoryExperimentStore()
    record = _record()
    await store.start(record)
    await store.finish(
        record.experiment_id,
        status=ExperimentStatus.FAILED,
        outcome=_outcome(),
    )

    with pytest.raises(ValueError, match="running"):
        await store.finish(
            record.experiment_id,
            status=ExperimentStatus.COMPLETED,
            outcome=_outcome(),
        )


@pytest.mark.anyio
async def test_list_filters_by_suite_newest_first() -> None:
    store = InMemoryExperimentStore()
    older = _record("agent-dev", age=20)
    other = _record("retrieval-dev", age=10)
    newer = _record("agent-dev")
    for record in (older, other, newer):
        await store.start(record)

    selected = await store.list(suite="agent-dev")

    assert selected == (newer, older)


def test_item_writer_private_lines(tmp_path) -> None:  # type: ignore[no-untyped-def]
    writer = ExperimentItemWriter(uuid4(), root=tmp_path)
    writer.append({"item_id": "one", "score": 0.5})
    writer.append({"item_id": "two", "score": 1})

    assert stat.S_IMODE(writer.path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(writer.path.stat().st_mode) == 0o600
    assert read_items(writer.path) == [
        {"item_id": "one", "score": 0.5},
        {"item_id": "two", "score": 1},
    ]
    assert writer.count == 2


def test_item_requires_item_id(tmp_path) -> None:  # type: ignore[no-untyped-def]
    writer = ExperimentItemWriter(uuid4(), root=tmp_path)

    with pytest.raises(ValueError, match="item_id"):
        writer.append({"score": 0.5})


def test_hardware_profile_keys() -> None:
    profile = hardware_profile()

    assert set(profile) == {
        "platform",
        "python_version",
        "cpu_count",
        "mem_total_mib",
        "gpu",
    }


def test_file_sha256(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "dataset.json"
    path.write_bytes(b"dataset marker")

    assert file_sha256(path) == hashlib.sha256(b"dataset marker").hexdigest()


def test_dataset_identity_is_frozen() -> None:
    identity = DatasetIdentity(name="fixture", version="v1", sha256="a" * 64)

    with pytest.raises(AttributeError):
        identity.name = "changed"  # type: ignore[misc]


@pytest.mark.anyio
async def test_missing_experiment_raises_not_found() -> None:
    with pytest.raises(ExperimentNotFound):
        await InMemoryExperimentStore().get(uuid4())
