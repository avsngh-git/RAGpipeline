"""Observability behavior tests."""

import json
import logging

from research_platform.observability.logging_config import JsonFormatter
from research_platform.observability.request_context import (
    bind_request_id,
    bind_run_id,
)


def test_json_formatter_emits_safe_request_fields() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request_completed",
        args=(),
        exc_info=None,
    )
    record.http_method = "GET"
    record.path = "/health"
    record.status_code = 200
    record.duration_ms = 1.25

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["message"] == "request_completed"
    assert payload["http_method"] == "GET"
    assert payload["path"] == "/health"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 1.25


def _record() -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="run_finished",
        args=(),
        exc_info=None,
    )


def test_run_fields_are_emitted() -> None:
    record = _record()
    record.run_id = "r-1"
    record.mode = "deep_research"
    record.status = "completed"
    record.duration_seconds = 1.25
    record.tool_calls = 2
    record.model_calls = 3

    payload = json.loads(JsonFormatter().format(record))

    for field in (
        "run_id",
        "mode",
        "status",
        "duration_seconds",
        "tool_calls",
        "model_calls",
    ):
        assert field in payload


def test_unknown_fields_are_dropped() -> None:
    record = _record()
    record.question = "private question"
    record.text = "passage"

    output = JsonFormatter().format(record)

    assert "question" not in output
    assert "text" not in output
    assert "private question" not in output
    assert "passage" not in output


def test_run_id_from_context() -> None:
    formatter = JsonFormatter()
    with bind_run_id("r-1"):
        inside = json.loads(formatter.format(_record()))
    outside = json.loads(formatter.format(_record()))

    assert inside["run_id"] == "r-1"
    assert "run_id" not in outside


def test_bind_request_id_none_is_noop() -> None:
    with bind_request_id("req-1"):
        with bind_request_id(None):
            assert (
                json.loads(JsonFormatter().format(_record()))["request_id"] == "req-1"
            )
