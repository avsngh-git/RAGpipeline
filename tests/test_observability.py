"""Observability behavior tests."""

import json
import logging

from research_platform.observability.logging_config import JsonFormatter


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
