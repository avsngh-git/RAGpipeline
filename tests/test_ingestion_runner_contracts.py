"""Runtime validation for ingestion runner contracts."""

from __future__ import annotations

import asyncio
from typing import cast
from uuid import uuid4

import pytest

from research_platform.ingestion.runner import (
    IngestionDocument,
    IngestionRunner,
    PipelineStage,
    StageOutcome,
    _validate_plan,
)
from research_platform.ingestion.stage_repository import IngestionJobRepository


def test_ingestion_document_requires_uuid_and_sha256_fingerprint() -> None:
    with pytest.raises(ValueError, match="document_id must be a UUID"):
        IngestionDocument("not-a-uuid", "sha256:" + "a" * 64)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="SHA-256 identity"):
        IngestionDocument(uuid4(), "invalid")


def test_stage_outcome_requires_json_compatible_mappings_and_fingerprint() -> None:
    with pytest.raises(ValueError, match="SHA-256 identity"):
        StageOutcome("invalid")

    fingerprint = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="output_references must be a mapping"):
        StageOutcome(fingerprint, output_references=["not", "a", "mapping"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite JSON-compatible values"):
        StageOutcome(fingerprint, resource_measurements={"peak_rss": float("nan")})


def test_runner_rejects_invalid_retry_reason_before_repository_access() -> None:
    document_id = uuid4()
    document = IngestionDocument(document_id, "sha256:" + "a" * 64)
    stage = PipelineStage("metadata", "sha256:" + "b" * 64, object())  # type: ignore[arg-type]
    runner = IngestionRunner(cast(IngestionJobRepository, object()))

    async def run_with_invalid_reason() -> None:
        with pytest.raises(ValueError, match="retry_reason must be non-empty text"):
            await runner.run(
                uuid4(),
                (document,),
                (stage,),
                retry_reason=123,  # type: ignore[arg-type]
            )

    asyncio.run(run_with_invalid_reason())


def test_runner_requires_retry_reason_for_targeted_retries() -> None:
    document_id = uuid4()
    document = IngestionDocument(document_id, "sha256:" + "a" * 64)
    stage = PipelineStage("metadata", "sha256:" + "b" * 64, object())  # type: ignore[arg-type]
    runner = IngestionRunner(cast(IngestionJobRepository, object()))

    async def run_without_reason() -> None:
        with pytest.raises(ValueError, match="targeted retries require"):
            await runner.run(
                uuid4(),
                (document,),
                (stage,),
                selected_document_ids=(document_id,),
            )

    asyncio.run(run_without_reason())


def test_runner_rejects_non_string_stage_names_clearly() -> None:
    document = IngestionDocument(uuid4(), "sha256:" + "a" * 64)
    stage = PipelineStage(1, "sha256:" + "b" * 64, object())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="lowercase identifiers"):
        _validate_plan((document,), (stage,))
