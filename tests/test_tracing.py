"""OpenTelemetry configuration and JSONL tracing tests."""

from __future__ import annotations

import base64
import json
import stat
from pathlib import Path

from research_platform.observability.content import TraceContent
from research_platform.observability.span_export import read_run_spans
from research_platform.observability.tracing import (
    ATTR_RUN_ID,
    TracingSettings,
    capture_spans,
    configure_tracing,
    get_tracer,
    set_id_attribute,
    set_text_attribute,
    shutdown_tracing,
    trace_content,
)


def test_capture_spans_collects_spans() -> None:
    with capture_spans() as exporter:
        with get_tracer().start_as_current_span("captured"):
            pass

    assert [span.name for span in exporter.get_finished_spans()] == ["captured"]


def test_capture_restores_previous_state() -> None:
    configure_tracing(
        TracingSettings(False, TraceContent.FULL, None, None),
        service_name="test",
    )
    try:
        with capture_spans(TraceContent.IDS):
            assert trace_content() is TraceContent.IDS
        assert trace_content() is TraceContent.FULL
    finally:
        shutdown_tracing()


def test_tracing_off_by_default_in_test() -> None:
    settings = TracingSettings.from_env("test", {})

    assert settings.enabled is False


def test_defaults_in_development() -> None:
    settings = TracingSettings.from_env("development", {})

    assert settings.enabled is True
    assert settings.content is TraceContent.FULL
    assert settings.jsonl_dir == Path("local-reference/traces")


def test_trace_dir_empty_disables_jsonl() -> None:
    settings = TracingSettings.from_env(
        "development", {"RESEARCH_PLATFORM_TRACE_DIR": ""}
    )

    assert settings.jsonl_dir is None


def test_otlp_headers_from_langfuse_keys() -> None:
    settings = TracingSettings.from_env(
        "test",
        {"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"},
    )
    headers = dict(settings.otlp_headers)

    encoded_credentials = headers["Authorization"].removeprefix("Basic ")
    assert base64.b64decode(encoded_credentials).decode() == "pk:sk"
    assert headers["x-langfuse-ingestion-version"] == "4"


def test_text_attribute_only_at_full() -> None:
    with capture_spans(TraceContent.IDS) as ids_exporter:
        with get_tracer().start_as_current_span("ids") as span:
            set_text_attribute(span, "text", "marker")
    assert "text" not in (ids_exporter.get_finished_spans()[0].attributes or {})

    with capture_spans(TraceContent.FULL) as full_exporter:
        with get_tracer().start_as_current_span("full") as span:
            set_text_attribute(span, "text", "marker")
    assert full_exporter.get_finished_spans()[0].attributes["text"] == "marker"


def test_id_attribute_skipped_at_none() -> None:
    with capture_spans(TraceContent.NONE) as exporter:
        with get_tracer().start_as_current_span("none") as span:
            set_id_attribute(span, "identifier", "synthetic-id")
            set_id_attribute(span, "missing", None)

    assert exporter.get_finished_spans()[0].attributes == {}


def test_jsonl_exporter_writes_private_lines(tmp_path: Path) -> None:
    configure_tracing(
        TracingSettings(True, TraceContent.IDS, tmp_path, None),
        service_name="test-api",
    )
    tracer = get_tracer()
    with tracer.start_as_current_span("research_run"):
        with tracer.start_as_current_span("child"):
            pass
    shutdown_tracing()

    path = tmp_path / "test-api.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 2
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert all(len(record["trace_id"]) == 32 for record in records)
    assert all(len(record["span_id"]) == 16 for record in records)
    child = next(record for record in records if record["name"] == "child")
    parent = next(record for record in records if record["name"] == "research_run")
    assert child["parent_span_id"] == parent["span_id"]


def test_read_run_spans_filters_by_run(tmp_path: Path) -> None:
    configure_tracing(
        TracingSettings(True, TraceContent.IDS, tmp_path, None),
        service_name="run-filter",
    )
    tracer = get_tracer()
    for run_id in ("run-a", "run-b"):
        with tracer.start_as_current_span("research_run") as span:
            set_id_attribute(span, ATTR_RUN_ID, run_id)
            with tracer.start_as_current_span("child"):
                pass
    shutdown_tracing()

    path = tmp_path / "run-filter.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")
    records = read_run_spans(path, run_id="run-a")

    assert len(records) == 2
    assert {record["name"] for record in records} == {"research_run", "child"}


def test_configure_twice_is_safe(tmp_path: Path) -> None:
    settings = TracingSettings(True, TraceContent.IDS, tmp_path, None)

    configure_tracing(settings, service_name="first")
    with get_tracer().start_as_current_span("first"):
        pass
    configure_tracing(settings, service_name="second")
    with get_tracer().start_as_current_span("second"):
        pass
    shutdown_tracing()

    assert (
        json.loads((tmp_path / "first.jsonl").read_text().splitlines()[0])["name"]
        == "first"
    )
    assert (
        json.loads((tmp_path / "second.jsonl").read_text().splitlines()[0])["name"]
        == "second"
    )
