"""Tests for stage-configuration identities and invalidation dependencies."""

import pytest

from research_platform.ingestion.stage_config import StageConfigurationIds


def _stage_id(digit: str) -> str:
    return f"sha256:{digit * 64}"


def _configuration(**changes: str) -> StageConfigurationIds:
    values = {
        "discovery": _stage_id("1"),
        "paper_import": _stage_id("2"),
        "acquisition": _stage_id("3"),
        "extraction": _stage_id("4"),
        "evidence": _stage_id("5"),
        "chunking": _stage_id("6"),
        "embedding": _stage_id("7"),
        "index": _stage_id("8"),
    }
    values.update(changes)
    return StageConfigurationIds(**values)


def test_stage_configuration_round_trip_has_stable_identity() -> None:
    configuration = _configuration()

    assert StageConfigurationIds.from_dict(configuration.to_dict()) == configuration
    assert StageConfigurationIds.from_dict(configuration.to_dict()).config_id == (
        configuration.config_id
    )


def test_chunking_change_invalidates_chunks_embeddings_and_index_only() -> None:
    previous = _configuration()
    current = _configuration(chunking=_stage_id("9"))

    assert current.invalidated_by(previous) == ("chunking", "embedding", "index")


def test_discovery_change_invalidates_every_dependent_stage() -> None:
    previous = _configuration()
    current = _configuration(discovery=_stage_id("9"))

    assert current.invalidated_by(previous) == (
        "discovery",
        "paper_import",
        "acquisition",
        "extraction",
        "evidence",
        "chunking",
        "embedding",
        "index",
    )


def test_identical_configuration_invalidates_no_stages() -> None:
    configuration = _configuration()

    assert configuration.invalidated_by(configuration) == ()


def test_invalid_stage_configurations_fail_clearly() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _configuration(index="not-a-hash")
    with pytest.raises(ValueError, match="unsupported"):
        StageConfigurationIds.from_dict({"schema_version": 2})
