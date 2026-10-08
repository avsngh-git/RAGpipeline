"""Spans never store exception text below content FULL (ADR-0026 content levels)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest
from opentelemetry.trace import StatusCode

from research_platform.observability.content import TraceContent
from research_platform.observability.tracing import (
    ATTR_ERROR_MESSAGE,
    ATTR_ERROR_TYPE,
    capture_spans,
    get_tracer,
)

_SECRET = "model output that must stay private"


def _raise_in_span(content: TraceContent) -> Any:
    with capture_spans(content) as exporter:
        with pytest.raises(ValueError):
            with get_tracer().start_as_current_span("node.example"):
                raise ValueError(f"input_value={_SECRET!r}")
    (span,) = exporter.get_finished_spans()
    return span


def _attributes(span: Any) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], span.attributes or {})


@pytest.mark.parametrize("content", [TraceContent.NONE, TraceContent.IDS])
def test_failed_span_holds_no_exception_text_below_full(content: TraceContent) -> None:
    span = _raise_in_span(content)

    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description is None
    assert span.events == ()
    assert _attributes(span)[ATTR_ERROR_TYPE] == "ValueError"
    assert ATTR_ERROR_MESSAGE not in _attributes(span)
    assert _SECRET not in repr(span.to_json())


def test_full_content_keeps_the_message_as_an_attribute() -> None:
    span = _raise_in_span(TraceContent.FULL)

    assert span.events == ()
    assert _SECRET in _attributes(span)[ATTR_ERROR_MESSAGE]


def test_caller_that_sets_its_own_status_is_left_alone() -> None:
    with capture_spans(TraceContent.IDS) as exporter:
        with pytest.raises(ValueError):
            with get_tracer().start_as_current_span(
                "llm.example", set_status_on_exception=False
            ):
                raise ValueError(_SECRET)
    (span,) = exporter.get_finished_spans()

    assert span.status.status_code is StatusCode.UNSET
    assert ATTR_ERROR_TYPE not in _attributes(span)


def test_spans_without_errors_are_unchanged() -> None:
    with capture_spans(TraceContent.IDS) as exporter:
        with get_tracer().start_as_current_span("node.ok") as span:
            span.set_attribute("research.node", "ok")
    (finished,) = exporter.get_finished_spans()

    assert finished.status.status_code is StatusCode.UNSET
    assert _attributes(finished) == {"research.node": "ok"}
