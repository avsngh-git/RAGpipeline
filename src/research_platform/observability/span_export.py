"""Private JSON Lines export for OpenTelemetry spans."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


def _utc_timestamp(value: int) -> str:
    return (
        datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def span_to_dict(span: ReadableSpan) -> dict[str, object]:
    """One span as a JSON-compatible dict."""
    context = span.context
    parent_context = span.parent
    start_ns = span.start_time
    end_ns = span.end_time
    if start_ns is None or end_ns is None:
        raise ValueError("Readable spans must have start and end times")
    start = _utc_timestamp(start_ns)
    end = _utc_timestamp(end_ns)
    return {
        "trace_id": f"{context.trace_id:032x}",
        "span_id": f"{context.span_id:016x}",
        "parent_span_id": (
            f"{parent_context.span_id:016x}" if parent_context is not None else None
        ),
        "name": span.name,
        "start": start,
        "end": end,
        "duration_ms": (end_ns - start_ns) / 1_000_000,
        "status": span.status.status_code.name,
        "status_message": span.status.description,
        "attributes": dict(span.attributes or {}),
        "events": [
            {
                "name": event.name,
                "timestamp": _utc_timestamp(event.timestamp),
                "attributes": dict(event.attributes or {}),
            }
            for event in span.events
        ],
    }


class JsonlSpanExporter(SpanExporter):
    """Append finished spans to a private JSON Lines file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            descriptor = os.open(
                self._path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                for span in spans:
                    stream.write(
                        json.dumps(span_to_dict(span), sort_keys=True, default=str)
                        + "\n"
                    )
        except OSError:
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """Nothing remains open between exports."""

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Exports are written synchronously, so there is nothing to flush."""
        return True


def read_run_spans(path: Path, *, run_id: str) -> list[dict[str, object]]:
    """Spans of every trace whose root carries research.run_id == run_id."""
    spans: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                spans.append(value)

    trace_ids: set[object] = set()
    for span in spans:
        attributes = span.get("attributes")
        if (
            span.get("name") == "research_run"
            and isinstance(attributes, dict)
            and attributes.get("research.run_id") == run_id
        ):
            trace_ids.add(span.get("trace_id"))
    return sorted(
        (span for span in spans if span.get("trace_id") in trace_ids),
        key=lambda span: str(span.get("start", "")),
    )
