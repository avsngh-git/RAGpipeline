"""Stable identity for the exact evidence selected by a snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from research_platform.ingestion.identity import is_valid_paper_id

_SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_CHUNK_SELECTION_SCHEMA_VERSION = 1


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256_ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a SHA-256 identity")
    return value


def _canonical_identity(configuration: object) -> str:
    canonical = json.dumps(
        configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SnapshotChunkSelection:
    """The extraction/chunk configuration selected for one snapshot member."""

    paper_id: str
    document_id: UUID
    extraction_id: UUID
    chunking_configuration_id: str | None

    def __post_init__(self) -> None:
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if not isinstance(self.document_id, UUID) or not isinstance(
            self.extraction_id, UUID
        ):
            raise ValueError("document_id and extraction_id must be UUIDs")
        if self.chunking_configuration_id is not None:
            _require_sha256(self.chunking_configuration_id, "chunking_configuration_id")

    def to_dict(self) -> dict[str, object]:
        return {
            "paper_id": self.paper_id,
            "document_id": str(self.document_id),
            "extraction_id": str(self.extraction_id),
            "chunking_configuration_id": self.chunking_configuration_id,
        }


def compute_chunk_selection_id(
    *,
    snapshot_id: UUID,
    snapshot_configuration_id: str,
    members: Sequence[SnapshotChunkSelection],
    selected_chunk_ids: Sequence[str],
) -> str:
    """Fingerprint exact source-member and chunk IDs without including source text."""
    if not isinstance(snapshot_id, UUID):
        raise ValueError("snapshot_id must be a UUID")
    _require_sha256(snapshot_configuration_id, "snapshot_configuration_id")
    normalized_members = tuple(members)
    if not normalized_members or any(
        not isinstance(member, SnapshotChunkSelection) for member in normalized_members
    ):
        raise ValueError("members must contain snapshot chunk selections")
    member_keys = tuple(
        (member.paper_id, member.document_id, member.extraction_id)
        for member in normalized_members
    )
    if len(set(member_keys)) != len(member_keys):
        raise ValueError("members must not contain duplicate paper/document selections")

    normalized_chunk_ids = tuple(selected_chunk_ids)
    if not normalized_chunk_ids:
        raise ValueError("selected_chunk_ids must not be empty")
    for chunk_id in normalized_chunk_ids:
        _require_sha256(chunk_id, "selected chunk ID")
    if len(set(normalized_chunk_ids)) != len(normalized_chunk_ids):
        raise ValueError("selected_chunk_ids must not contain duplicates")

    configuration = {
        "schema_version": _CHUNK_SELECTION_SCHEMA_VERSION,
        "snapshot_id": str(snapshot_id),
        "snapshot_configuration_id": snapshot_configuration_id,
        "members": [
            member.to_dict()
            for member in sorted(
                normalized_members,
                key=lambda item: (
                    item.paper_id,
                    str(item.document_id),
                    str(item.extraction_id),
                ),
            )
        ],
        "selected_chunk_ids": sorted(normalized_chunk_ids),
    }
    return _canonical_identity(configuration)
