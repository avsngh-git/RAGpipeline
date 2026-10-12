"""Encoding for snapshot-bound citation graph cursors."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Final
from uuid import UUID

from research_platform.search.paper_graph import CitationDirection, CitationGraphCursor
from research_platform.services.errors import AppError

MAX_CURSOR_CHARS: Final = 2048


def encode_cursor(cursor: CitationGraphCursor | None) -> str | None:
    if cursor is None:
        return None
    payload = {
        "snapshot_id": str(cursor.snapshot_id),
        "paper_id": cursor.paper_id,
        "direction": cursor.direction.value,
        "endpoint_kind": cursor.endpoint_kind,
        "endpoint_identifier": cursor.endpoint_identifier,
        "edge_source": cursor.edge_source,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(
    value: str | None,
    *,
    snapshot_id: UUID,
    paper_id: str,
    direction: CitationDirection,
) -> CitationGraphCursor | None:
    if value is None:
        return None
    if not value or len(value) > MAX_CURSOR_CHARS:
        raise AppError("invalid_cursor", "The citation cursor is invalid.", 422)
    try:
        encoded = value.encode("ascii")
        padding = b"=" * (-len(encoded) % 4)
        raw = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {
            "snapshot_id",
            "paper_id",
            "direction",
            "endpoint_kind",
            "endpoint_identifier",
            "edge_source",
        }:
            raise ValueError
        cursor = CitationGraphCursor(
            snapshot_id=UUID(payload["snapshot_id"]),
            paper_id=payload["paper_id"],
            direction=CitationDirection(payload["direction"]),
            endpoint_kind=payload["endpoint_kind"],
            endpoint_identifier=payload["endpoint_identifier"],
            edge_source=payload["edge_source"],
        )
    except (
        UnicodeEncodeError,
        binascii.Error,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        KeyError,
    ):
        raise AppError(
            "invalid_cursor", "The citation cursor is invalid.", 422
        ) from None
    if (
        cursor.snapshot_id != snapshot_id
        or cursor.paper_id != paper_id
        or cursor.direction is not direction
    ):
        raise AppError(
            "invalid_cursor", "The citation cursor does not match this request.", 422
        )
    return cursor
