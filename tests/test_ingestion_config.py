"""Tests for ingestion configuration value objects."""

import json
from dataclasses import FrozenInstanceError

import pytest

from research_platform.ingestion.config import (
    DiscoveryConfig,
    DiscoveryLimits,
    YearRange,
)


def test_year_range_accepts_increasing_years() -> None:
    year_range = YearRange(start_year=2020, end_year=2026)

    assert year_range.start_year == 2020
    assert year_range.end_year == 2026


def test_year_range_accepts_same_year() -> None:
    year_range = YearRange(start_year=2024, end_year=2024)

    assert year_range.start_year == year_range.end_year == 2024


def test_year_range_rejects_reversed_years() -> None:
    with pytest.raises(
        ValueError, match="start_year must be less than or equal to end_year"
    ):
        YearRange(start_year=2026, end_year=2020)


def test_year_range_is_immutable() -> None:
    year_range = YearRange(start_year=2020, end_year=2026)

    with pytest.raises(FrozenInstanceError):
        setattr(year_range, "start_year", 2021)


def test_discovery_config_accepts_queries_and_defaults_to_english() -> None:
    year_range = YearRange(start_year=2020, end_year=2026)

    config = DiscoveryConfig(queries=("hybrid retrieval",), year_range=year_range)

    assert config.queries == ("hybrid retrieval",)
    assert config.year_range == year_range
    assert config.language == "en"


@pytest.mark.parametrize("queries", [(), ("",), ("   ",)])
def test_discovery_config_rejects_missing_or_blank_queries(
    queries: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        DiscoveryConfig(
            queries=queries,
            year_range=YearRange(start_year=2020, end_year=2026),
        )


def test_discovery_config_rejects_non_english_language() -> None:
    with pytest.raises(ValueError):
        DiscoveryConfig(
            queries=("hybrid retrieval",),
            year_range=YearRange(start_year=2020, end_year=2026),
            language="de",
        )


def test_discovery_config_round_trips_through_json_compatible_dict() -> None:
    config = DiscoveryConfig(
        queries=("hybrid retrieval", "reranking"),
        year_range=YearRange(start_year=2020, end_year=2026),
    )

    serialized = config.to_dict()
    decoded = json.loads(json.dumps(serialized))

    assert serialized["queries"] == ["hybrid retrieval", "reranking"]
    assert DiscoveryConfig.from_dict(decoded) == config


def test_discovery_config_has_stable_identity() -> None:
    config = DiscoveryConfig(
        queries=("hybrid retrieval",),
        year_range=YearRange(start_year=2020, end_year=2026),
    )
    equivalent_config = DiscoveryConfig.from_dict(config.to_dict())

    assert config.config_id.startswith("sha256:")
    assert equivalent_config.config_id == config.config_id


def test_discovery_config_identity_changes_when_effective_input_changes() -> None:
    config = DiscoveryConfig(
        queries=("hybrid retrieval",),
        year_range=YearRange(start_year=2020, end_year=2026),
    )
    changed_config = DiscoveryConfig(
        queries=("dense retrieval",),
        year_range=YearRange(start_year=2020, end_year=2026),
    )

    assert changed_config.config_id != config.config_id


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"schema_version": 1, "queries": [], "year_range": {}, "language": "en"},
        {
            "schema_version": 1,
            "queries": ["hybrid retrieval"],
            "year_range": {"start_year": True, "end_year": 2026},
            "language": "en",
        },
        {
            "schema_version": 2,
            "queries": ["hybrid retrieval"],
            "year_range": {"start_year": 2020, "end_year": 2026},
            "language": "en",
        },
    ],
)
def test_discovery_config_rejects_invalid_serialized_data(
    data: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        DiscoveryConfig.from_dict(data)


def test_discovery_limits_validate_page_retry_and_rate_bounds() -> None:
    with pytest.raises(ValueError, match="per_page"):
        DiscoveryLimits(per_page=101)
    with pytest.raises(ValueError, match="max_retries"):
        DiscoveryLimits(max_retries=-1)
    with pytest.raises(ValueError, match="minimum_request_interval"):
        DiscoveryLimits(minimum_request_interval_seconds=0.5)


def test_config_canonicalizes_older_exception_ids_and_hashes_limits() -> None:
    config_from_url = DiscoveryConfig(
        queries=("hybrid retrieval",),
        year_range=YearRange(start_year=2020, end_year=2026),
        older_paper_exceptions=("https://openalex.org/W17",),
    )
    config_from_id = DiscoveryConfig(
        queries=("hybrid retrieval",),
        year_range=YearRange(start_year=2020, end_year=2026),
        older_paper_exceptions=("W17",),
    )
    changed_limits = DiscoveryConfig(
        queries=("hybrid retrieval",),
        year_range=YearRange(start_year=2020, end_year=2026),
        older_paper_exceptions=("W17",),
        limits=DiscoveryLimits(max_total_requests=20),
    )

    assert config_from_url.older_paper_exceptions == ("W17",)
    assert config_from_url.config_id == config_from_id.config_id
    assert changed_limits.config_id != config_from_id.config_id
    assert DiscoveryConfig.from_dict(config_from_id.to_dict()) == config_from_id


def test_discovery_config_is_immutable() -> None:
    config = DiscoveryConfig(
        queries=("hybrid retrieval",),
        year_range=YearRange(start_year=2020, end_year=2026),
    )

    with pytest.raises(FrozenInstanceError):
        setattr(config, "language", "de")
