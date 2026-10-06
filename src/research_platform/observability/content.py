"""Trace content policy configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from typing import Final


class TraceContent(StrEnum):
    """How much content traces and run payloads may hold."""

    NONE = "none"
    IDS = "ids"
    FULL = "full"


TRACE_CONTENT_ENV: Final = "RESEARCH_PLATFORM_TRACE_CONTENT"


def trace_content_from_env(
    environment: str, environ: Mapping[str, str] | None = None
) -> TraceContent:
    """The explicit setting, else ``full`` in development and ``ids`` elsewhere."""
    source = os.environ if environ is None else environ
    value = source.get(TRACE_CONTENT_ENV)
    if value is None or not value.strip():
        content = (
            TraceContent.FULL if environment == "development" else TraceContent.IDS
        )
    else:
        normalized = value.strip().lower()
        try:
            content = TraceContent(normalized)
        except ValueError as exc:
            raise ValueError(
                "RESEARCH_PLATFORM_TRACE_CONTENT must be none, ids or full"
            ) from exc
    if environment == "production" and content is TraceContent.FULL:
        raise ValueError("full trace content is not allowed in production")
    return content
