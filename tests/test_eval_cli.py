from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from research_platform.config import Settings
from research_platform.evaluation.cli import _parser
from research_platform.evaluation.experiments import (
    DatasetIdentity,
    ExperimentOutcome,
    ExperimentStatus,
    InMemoryExperimentStore,
    file_sha256,
    read_items,
)
from research_platform.evaluation.suites import SUITES
from research_platform.evaluation.suites.base import SuiteContext, run_suite
from research_platform.evaluation.suites.scripted_regression import (
    CASE_PATH,
    ScriptedRegressionSuite,
)


@pytest.mark.anyio
async def test_scripted_regression_suite_records_experiment(tmp_path: Path) -> None:
    store = InMemoryExperimentStore()
    record = await run_suite(
        ScriptedRegressionSuite(),
        store=store,
        settings=Settings(environment="test"),
        options={},
        items_root=tmp_path,
    )

    assert record.status is ExperimentStatus.COMPLETED
    assert record.metrics["cases"] == 33
    assert record.metrics["pass_rate"] == 1.0
    assert record.item_count == 33
    assert len(read_items(Path(record.items_path))) == 33
    assert len(record.dataset_sha256) == 64
    assert all(character in "0123456789abcdef" for character in record.dataset_sha256)


class _FailingSuite:
    name = "failing"

    def dataset(self, options: Mapping[str, str]) -> DatasetIdentity:
        return DatasetIdentity("test", "v1", "0" * 64)

    async def run(self, context: SuiteContext) -> ExperimentOutcome:
        raise RuntimeError("synthetic failure")


@pytest.mark.anyio
async def test_failed_suite_records_failure(tmp_path: Path) -> None:
    store = InMemoryExperimentStore()
    with pytest.raises(RuntimeError, match="synthetic failure"):
        await run_suite(
            _FailingSuite(),
            store=store,
            settings=Settings(environment="test"),
            options={},
            items_root=tmp_path,
        )

    (record,) = await store.list()
    assert record.status is ExperimentStatus.FAILED
    assert record.failures == {"RuntimeError": 1}


def test_option_parsing_rejects_missing_equals() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(["run", "scripted-regression", "--option", "missing"])


def test_registry_contains_scripted_regression() -> None:
    assert "scripted-regression" in SUITES
    assert isinstance(SUITES["scripted-regression"], ScriptedRegressionSuite)


def test_case_path_exists() -> None:
    assert CASE_PATH.is_file()
    assert len(file_sha256(CASE_PATH)) == 64
