"""Encoding for run-history keyset cursors."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Final
from uuid import UUID

from research_platform.services.errors import AppError

MAX_CURSOR_CHARS: Final = 512


def encode_run_cursor(created_at: datetime, run_id: UUID) -> str:
    """Encode a run's creation time and identifier as an opaque cursor."""
    payload = {"created_at": created_at.isoformat(), "run_id": str(run_id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_run_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    """Decode a run-history cursor or raise a stable validation error."""
    if value is None:
        return None
    if not value or len(value) > MAX_CURSOR_CHARS:
        raise _invalid_cursor()
    try:
        encoded = value.encode("ascii")
        raw = base64.b64decode(
            encoded + b"=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"created_at", "run_id"}:
            raise ValueError
        created_at = datetime.fromisoformat(payload["created_at"])
        run_id = UUID(payload["run_id"])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
    except (
        UnicodeEncodeError,
        binascii.Error,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        KeyError,
    ):
        raise _invalid_cursor() from None
    return created_at, run_id


def _invalid_cursor() -> AppError:
    return AppError("invalid_cursor", "The cursor is invalid.", 422)
