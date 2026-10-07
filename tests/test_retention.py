"""Unit tests for retention policy and command output."""

from __future__ import annotations

import json
from argparse import Namespace
from uuid import uuid4

import pytest

from research_platform.maintenance import cli
from research_platform.maintenance.retention import (
    RetentionPolicy,
    RetentionReport,
    UnpublishedGeneration,
)


@pytest.mark.parametrize(
    "values",
    [
        {"completed_checkpoint_days": 0},
        {"failed_checkpoint_days": 0},
        {"llm_payload_days": 0},
        {"completed_checkpoint_days": -1},
        {"llm_payload_days": True},
    ],
)
def test_policy_validation(values: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RetentionPolicy(**values)  # type: ignore[arg-type]


def test_report_json_shape() -> None:
    collection_id = uuid4()
    report = RetentionReport(
        dry_run=True,
        checkpoint_runs=(uuid4(), uuid4()),
        llm_payloads=3,
        retired_points=None,
        unpublished_generations=(
            UnpublishedGeneration(
                collection_id=collection_id,
                configuration_id="sha256:fixture",
                generation=4,
                state="failed",
                point_count=7,
            ),
        ),
    )

    assert report.to_json() == {
        "dry_run": True,
        "checkpoint_run_count": 2,
        "llm_payloads": 3,
        "retired_points": None,
        "unpublished_generations": [
            {
                "collection_id": str(collection_id),
                "configuration_id": "sha256:fixture",
                "generation": 4,
                "state": "failed",
                "point_count": 7,
            }
        ],
    }


def test_cli_defaults_to_dry_run(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    run_id = uuid4()

    class Pool:
        async def close(self) -> None:
            return None

    pool = Pool()

    async def create_pool(*_args: object, **_kwargs: object) -> Pool:
        return pool

    async def expired_runs(*_args: object) -> tuple:
        return (run_id,)

    async def payload_count(*_args: object) -> int:
        return 2

    async def no_unpublished(*_args: object) -> tuple:
        return ()

    async def should_not_delete(*_args: object) -> int:
        raise AssertionError("dry-run called a delete function")

    monkeypatch.setattr(cli.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(cli, "Settings", lambda: Namespace(database_url="db"))
    monkeypatch.setattr(cli, "expired_checkpoint_runs", expired_runs)
    monkeypatch.setattr(cli, "expired_llm_payloads", payload_count)
    monkeypatch.setattr(cli, "unpublished_generations", no_unpublished)
    monkeypatch.setattr(cli, "delete_expired_llm_payloads", should_not_delete)
    monkeypatch.setattr(cli, "delete_run_checkpoints", should_not_delete)

    cli.main(["retention"])

    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["checkpoint_run_count"] == 1
    assert output["llm_payloads"] == 2


def test_retention_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["retention", "--help"])

    assert exc_info.value.code == 0
