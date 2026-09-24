"""Stable stage identities and downstream invalidation rules."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypedDict

PipelineStage = Literal[
    "discovery",
    "paper_import",
    "acquisition",
    "extraction",
    "evidence",
    "chunking",
    "embedding",
    "index",
]

_STAGE_INVALIDATIONS: dict[PipelineStage, tuple[PipelineStage, ...]] = {
    "discovery": (
        "discovery",
        "paper_import",
        "acquisition",
        "extraction",
        "evidence",
        "chunking",
        "embedding",
        "index",
    ),
    "paper_import": (
        "paper_import",
        "acquisition",
        "extraction",
        "evidence",
        "chunking",
        "embedding",
        "index",
    ),
    "acquisition": (
        "acquisition",
        "extraction",
        "evidence",
        "chunking",
        "embedding",
        "index",
    ),
    "extraction": (
        "extraction",
        "evidence",
        "chunking",
        "embedding",
        "index",
    ),
    "evidence": ("evidence", "chunking", "embedding", "index"),
    "chunking": ("chunking", "embedding", "index"),
    "embedding": ("embedding", "index"),
    "index": ("index",),
}


class StageConfigurationIdsDict(TypedDict):
    schema_version: Literal[1]
    discovery: str
    paper_import: str
    acquisition: str
    extraction: str
    evidence: str
    chunking: str
    embedding: str
    index: str


@dataclass(frozen=True)
class StageConfigurationIds:
    """Configuration hashes associated with the inputs to each pipeline stage."""

    discovery: str
    paper_import: str
    acquisition: str
    extraction: str
    evidence: str
    chunking: str
    embedding: str
    index: str

    def __post_init__(self) -> None:
        for stage, identifier in self.to_stage_mapping().items():
            if not isinstance(identifier, str) or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", identifier
            ):
                raise ValueError(f"{stage} configuration ID must be a SHA-256 identity")

    def to_stage_mapping(self) -> dict[PipelineStage, str]:
        return {
            "discovery": self.discovery,
            "paper_import": self.paper_import,
            "acquisition": self.acquisition,
            "extraction": self.extraction,
            "evidence": self.evidence,
            "chunking": self.chunking,
            "embedding": self.embedding,
            "index": self.index,
        }

    def to_dict(self) -> StageConfigurationIdsDict:
        return {
            "schema_version": 1,
            "discovery": self.discovery,
            "paper_import": self.paper_import,
            "acquisition": self.acquisition,
            "extraction": self.extraction,
            "evidence": self.evidence,
            "chunking": self.chunking,
            "embedding": self.embedding,
            "index": self.index,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> StageConfigurationIds:
        if data.get("schema_version") != 1 or isinstance(
            data.get("schema_version"), bool
        ):
            raise ValueError("unsupported stage configuration schema version")
        stage_names = set(_STAGE_INVALIDATIONS)
        if set(data) != stage_names | {"schema_version"}:
            raise ValueError("stage configuration fields are incomplete or unknown")
        if any(not isinstance(data[stage], str) for stage in stage_names):
            raise ValueError("stage configuration IDs must be strings")
        return cls(
            discovery=data["discovery"],  # type: ignore[arg-type]
            paper_import=data["paper_import"],  # type: ignore[arg-type]
            acquisition=data["acquisition"],  # type: ignore[arg-type]
            extraction=data["extraction"],  # type: ignore[arg-type]
            evidence=data["evidence"],  # type: ignore[arg-type]
            chunking=data["chunking"],  # type: ignore[arg-type]
            embedding=data["embedding"],  # type: ignore[arg-type]
            index=data["index"],  # type: ignore[arg-type]
        )

    @property
    def config_id(self) -> str:
        canonical = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    def invalidated_by(
        self, previous: StageConfigurationIds
    ) -> tuple[PipelineStage, ...]:
        """List every stage whose output must be rebuilt after a config change."""
        current_values = self.to_stage_mapping()
        previous_values = previous.to_stage_mapping()
        invalidated: set[PipelineStage] = set()
        for stage, current_id in current_values.items():
            if current_id != previous_values[stage]:
                invalidated.update(_STAGE_INVALIDATIONS[stage])
        stage_order = tuple(_STAGE_INVALIDATIONS)
        return tuple(stage for stage in stage_order if stage in invalidated)
