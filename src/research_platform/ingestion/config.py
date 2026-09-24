"""Typed, serializable configuration for ingestion discovery."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Literal, TypedDict


class YearRangeDict(TypedDict):
    start_year: int
    end_year: int


class DiscoveryLimitsDict(TypedDict):
    per_page: int
    max_pages_per_query: int
    max_total_requests: int
    max_retries: int
    timeout_seconds: float
    minimum_request_interval_seconds: float


class DiscoveryConfigDict(TypedDict):
    schema_version: Literal[1]
    queries: list[str]
    year_range: YearRangeDict
    language: str
    older_paper_exceptions: list[str]
    limits: DiscoveryLimitsDict


@dataclass(frozen=True)
class YearRange:
    start_year: int
    end_year: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.start_year, bool)
            or not isinstance(self.start_year, int)
            or isinstance(self.end_year, bool)
            or not isinstance(self.end_year, int)
            or not 1 <= self.start_year <= 9999
            or not 1 <= self.end_year <= 9999
        ):
            raise ValueError("years must be integers from 1 through 9999")
        if self.start_year > self.end_year:
            raise ValueError("start_year must be less than or equal to end_year")


@dataclass(frozen=True)
class DiscoveryLimits:
    """Conservative request and retry limits for one discovery run."""

    per_page: int = 100
    max_pages_per_query: int = 10
    max_total_requests: int = 50
    max_retries: int = 2
    timeout_seconds: float = 15.0
    minimum_request_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        for field_name, value in (
            ("per_page", self.per_page),
            ("max_pages_per_query", self.max_pages_per_query),
            ("max_total_requests", self.max_total_requests),
            ("max_retries", self.max_retries),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
        if not 1 <= self.per_page <= 100:
            raise ValueError("per_page must be between 1 and 100")
        if self.max_pages_per_query <= 0:
            raise ValueError("max_pages_per_query must be positive")
        if self.max_total_requests <= 0:
            raise ValueError("max_total_requests must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        if (
            isinstance(self.minimum_request_interval_seconds, bool)
            or not isinstance(self.minimum_request_interval_seconds, (int, float))
            or not isfinite(self.minimum_request_interval_seconds)
            or self.minimum_request_interval_seconds < 1.0
        ):
            raise ValueError("minimum_request_interval_seconds must be at least 1")

    def to_dict(self) -> DiscoveryLimitsDict:
        return {
            "per_page": self.per_page,
            "max_pages_per_query": self.max_pages_per_query,
            "max_total_requests": self.max_total_requests,
            "max_retries": self.max_retries,
            "timeout_seconds": float(self.timeout_seconds),
            "minimum_request_interval_seconds": float(
                self.minimum_request_interval_seconds
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> DiscoveryLimits:
        expected_keys = {
            "per_page",
            "max_pages_per_query",
            "max_total_requests",
            "max_retries",
            "timeout_seconds",
            "minimum_request_interval_seconds",
        }
        if set(data) != expected_keys:
            raise ValueError(
                "discovery limit fields must be exactly "
                + ", ".join(sorted(expected_keys))
            )
        integer_fields = (
            "per_page",
            "max_pages_per_query",
            "max_total_requests",
            "max_retries",
        )
        if any(
            isinstance(data[field_name], bool) or not isinstance(data[field_name], int)
            for field_name in integer_fields
        ):
            raise ValueError("discovery request limits must be integers")
        timeout = data["timeout_seconds"]
        interval = data["minimum_request_interval_seconds"]
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or isinstance(interval, bool)
            or not isinstance(interval, (int, float))
        ):
            raise ValueError("discovery time limits must be numbers")
        return cls(
            per_page=data["per_page"],  # type: ignore[arg-type]
            max_pages_per_query=data["max_pages_per_query"],  # type: ignore[arg-type]
            max_total_requests=data["max_total_requests"],  # type: ignore[arg-type]
            max_retries=data["max_retries"],  # type: ignore[arg-type]
            timeout_seconds=float(timeout),
            minimum_request_interval_seconds=float(interval),
        )


@dataclass(frozen=True)
class DiscoveryConfig:
    queries: tuple[str, ...]
    year_range: YearRange
    language: str = "en"
    older_paper_exceptions: tuple[str, ...] = ()
    limits: DiscoveryLimits = DiscoveryLimits()

    def __post_init__(self) -> None:
        if not isinstance(self.queries, tuple) or not self.queries:
            raise ValueError("queries must be a non-empty tuple of strings")
        if any(
            not isinstance(query, str) or not query.strip() or len(query) > 200
            for query in self.queries
        ):
            raise ValueError("queries must be non-empty strings up to 200 characters")
        if not isinstance(self.year_range, YearRange):
            raise ValueError("year_range must be a YearRange")
        if self.language != "en":
            raise ValueError("language must be english ('en')")
        if not isinstance(self.older_paper_exceptions, tuple):
            raise ValueError("older_paper_exceptions must be a tuple of OpenAlex IDs")
        normalized_exceptions: list[str] = []
        for identifier in self.older_paper_exceptions:
            if not isinstance(identifier, str):
                raise ValueError("older-paper exceptions must be OpenAlex work IDs")
            normalized = identifier.removeprefix("https://openalex.org/").strip()
            if not re.fullmatch(r"W[0-9]+", normalized):
                raise ValueError("older-paper exceptions must be OpenAlex work IDs")
            normalized_exceptions.append(normalized)
        if len(set(normalized_exceptions)) != len(normalized_exceptions):
            raise ValueError("older-paper exceptions must not contain duplicates")
        object.__setattr__(self, "older_paper_exceptions", tuple(normalized_exceptions))
        if not isinstance(self.limits, DiscoveryLimits):
            raise ValueError("limits must be DiscoveryLimits")

    def to_dict(self) -> DiscoveryConfigDict:
        """Return a JSON-compatible representation of this configuration."""
        return {
            "schema_version": 1,
            "queries": list(self.queries),
            "year_range": {
                "start_year": self.year_range.start_year,
                "end_year": self.year_range.end_year,
            },
            "language": self.language,
            "older_paper_exceptions": list(self.older_paper_exceptions),
            "limits": self.limits.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> DiscoveryConfig:
        """Build a validated configuration from its serialized representation."""
        expected_keys = {
            "schema_version",
            "queries",
            "year_range",
            "language",
            "older_paper_exceptions",
            "limits",
        }
        if set(data) != expected_keys:
            raise ValueError(
                "configuration fields must be exactly "
                + ", ".join(sorted(expected_keys))
            )
        if data["schema_version"] != 1 or isinstance(data["schema_version"], bool):
            raise ValueError("unsupported discovery configuration schema_version")

        queries_value = data["queries"]
        if not isinstance(queries_value, list) or not all(
            isinstance(query, str) for query in queries_value
        ):
            raise ValueError("queries must be a list of strings")

        year_range_value = data["year_range"]
        if not isinstance(year_range_value, Mapping) or set(year_range_value) != {
            "start_year",
            "end_year",
        }:
            raise ValueError("year_range must contain start_year and end_year")
        start_year = year_range_value["start_year"]
        end_year = year_range_value["end_year"]
        if (
            isinstance(start_year, bool)
            or not isinstance(start_year, int)
            or isinstance(end_year, bool)
            or not isinstance(end_year, int)
        ):
            raise ValueError("year_range values must be integers")

        language_value = data["language"]
        if not isinstance(language_value, str):
            raise ValueError("language must be a string")
        exceptions_value = data["older_paper_exceptions"]
        if not isinstance(exceptions_value, list) or not all(
            isinstance(identifier, str) for identifier in exceptions_value
        ):
            raise ValueError("older_paper_exceptions must be a list of identifiers")
        limits_value = data["limits"]
        if not isinstance(limits_value, Mapping):
            raise ValueError("limits must be an object")

        return cls(
            queries=tuple(queries_value),
            year_range=YearRange(start_year=start_year, end_year=end_year),
            language=language_value,
            older_paper_exceptions=tuple(exceptions_value),
            limits=DiscoveryLimits.from_dict(limits_value),
        )

    @property
    def config_id(self) -> str:
        """Return a stable SHA-256 identity for the effective serialized inputs."""
        canonical = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"
