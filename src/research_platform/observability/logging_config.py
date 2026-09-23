"""Structured JSON logging configuration."""

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from .request_context import get_request_id


class JsonFormatter(logging.Formatter):
    """Format selected safe log fields as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = get_request_id() or getattr(record, "request_id", None)
        if request_id is not None:
            payload["request_id"] = request_id

        for field_name in ("http_method", "path", "status_code", "duration_ms"):
            if hasattr(record, field_name):
                payload[field_name] = getattr(record, field_name)

        if record.exc_info is not None:
            exception_type, _, exception_traceback = record.exc_info
            payload["exception"] = {
                "type": exception_type.__name__ if exception_type else "Exception",
                "frames": [
                    {
                        "file": frame.filename.rsplit("/", maxsplit=1)[-1],
                        "line": frame.lineno,
                        "function": frame.name,
                    }
                    for frame in traceback.extract_tb(exception_traceback, limit=12)
                ],
            }

        return json.dumps(payload, sort_keys=True)


def configure_logging(log_level: str = "INFO") -> None:
    """Configure one reusable JSON handler on the process root logger."""

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())

    handler = next(
        (
            candidate
            for candidate in root_logger.handlers
            if candidate.get_name() == "research_platform_json"
        ),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler()
        handler.set_name("research_platform_json")
        root_logger.addHandler(handler)

    handler.setFormatter(JsonFormatter())
