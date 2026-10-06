"""Trace content configuration follows environment-safe defaults."""

import pytest

from research_platform.observability.content import (
    TraceContent,
    trace_content_from_env,
)


def test_default_full_in_development() -> None:
    assert trace_content_from_env("development", {}) is TraceContent.FULL


def test_default_ids_in_test_and_production() -> None:
    assert trace_content_from_env("test", {}) is TraceContent.IDS
    assert trace_content_from_env("production", {}) is TraceContent.IDS


def test_explicit_value_wins() -> None:
    assert (
        trace_content_from_env(
            "development", {"RESEARCH_PLATFORM_TRACE_CONTENT": " none "}
        )
        is TraceContent.NONE
    )


def test_invalid_value_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="RESEARCH_PLATFORM_TRACE_CONTENT must be none, ids or full",
    ):
        trace_content_from_env("test", {"RESEARCH_PLATFORM_TRACE_CONTENT": "verbose"})


def test_full_rejected_in_production() -> None:
    with pytest.raises(
        ValueError, match="full trace content is not allowed in production"
    ):
        trace_content_from_env(
            "production", {"RESEARCH_PLATFORM_TRACE_CONTENT": "full"}
        )
