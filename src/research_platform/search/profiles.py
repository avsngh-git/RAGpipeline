"""Canonical, snapshot-bound retrieval profile identities."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields, is_dataclass
from typing import Any, Literal, TypeVar, cast
from uuid import UUID

from research_platform.ingestion.snapshot_selection import (
    SnapshotChunkSelection,
    compute_chunk_selection_id,
)
from research_platform.search.contracts import DEFAULT_SEARCH_LIMITS

_SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROFILE_SCHEMA_VERSION = 1
_ConfigT = TypeVar("_ConfigT")


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256_ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a SHA-256 identity")
    return value


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_object(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    return cast(Mapping[str, object], value)


def _require_fields(data: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(data) != expected:
        raise ValueError(f"{name} fields are incomplete or unknown")


def _plain_json(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _plain_json(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    return value


def _dataclass_dict(value: object) -> dict[str, object]:
    result = _plain_json(value)
    if not isinstance(result, dict):
        raise TypeError("profile configuration did not serialize to an object")
    return cast(dict[str, object], result)


def _canonical_identity(configuration: Mapping[str, object]) -> str:
    canonical = json.dumps(
        _plain_json(configuration),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _from_dataclass(
    config_type: type[_ConfigT], data: Mapping[str, object], name: str
) -> _ConfigT:
    if not is_dataclass(config_type):
        raise TypeError("configuration type must be a dataclass")
    expected = {field.name for field in fields(cast(Any, config_type))}
    _require_fields(data, expected, name)
    try:
        return cast(_ConfigT, cast(Any, config_type)(**dict(data)))
    except TypeError:
        raise ValueError(f"{name} configuration is malformed") from None


@dataclass(frozen=True)
class SnapshotSelection:
    """Immutable snapshot and exact searchable chunk-set identity."""

    snapshot_id: UUID
    snapshot_configuration_id: str
    chunk_selection_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, UUID):
            raise ValueError("snapshot_id must be a UUID")
        _require_sha256(self.snapshot_configuration_id, "snapshot_configuration_id")
        _require_sha256(self.chunk_selection_id, "chunk_selection_id")

    @classmethod
    def from_members(
        cls,
        *,
        snapshot_id: UUID,
        snapshot_configuration_id: str,
        members: Sequence[SnapshotChunkSelection],
        selected_chunk_ids: Sequence[str],
    ) -> SnapshotSelection:
        return cls(
            snapshot_id=snapshot_id,
            snapshot_configuration_id=snapshot_configuration_id,
            chunk_selection_id=compute_chunk_selection_id(
                snapshot_id=snapshot_id,
                snapshot_configuration_id=snapshot_configuration_id,
                members=members,
                selected_chunk_ids=selected_chunk_ids,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return _dataclass_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> SnapshotSelection:
        _require_fields(
            data,
            {"snapshot_id", "snapshot_configuration_id", "chunk_selection_id"},
            "snapshot selection",
        )
        raw_snapshot_id = data["snapshot_id"]
        if not isinstance(raw_snapshot_id, str):
            raise ValueError("snapshot_id must be a UUID")
        try:
            snapshot_id = UUID(raw_snapshot_id)
        except ValueError:
            raise ValueError("snapshot_id must be a UUID") from None
        return cls(
            snapshot_id=snapshot_id,
            snapshot_configuration_id=cast(str, data["snapshot_configuration_id"]),
            chunk_selection_id=cast(str, data["chunk_selection_id"]),
        )


@dataclass(frozen=True)
class LexicalIndexIdentity:
    """Reproducible lexical implementation, analyzer, and index-format choices."""

    implementation: str
    implementation_revision: str
    analyzer: str
    analyzer_revision: str
    normalization_revision: str
    index_format_revision: str

    def __post_init__(self) -> None:
        for name in (
            "implementation",
            "implementation_revision",
            "analyzer",
            "analyzer_revision",
            "normalization_revision",
            "index_format_revision",
        ):
            _require_text(getattr(self, name), name)

    @property
    def configuration_id(self) -> str:
        return _canonical_identity(_dataclass_dict(self))


@dataclass(frozen=True)
class DenseIndexIdentity:
    """Embedding/model and existing vector-index compatibility identities."""

    model: str
    revision: str
    preprocessing_revision: str
    dimensions: int
    maximum_input_tokens: int
    index_configuration_id: str

    def __post_init__(self) -> None:
        for name in ("model", "revision", "preprocessing_revision"):
            _require_text(getattr(self, name), name)
        _require_positive_integer(self.dimensions, "dimensions")
        _require_positive_integer(self.maximum_input_tokens, "maximum_input_tokens")
        _require_sha256(self.index_configuration_id, "index_configuration_id")


@dataclass(frozen=True)
class RerankerIdentity:
    """Model and preprocessing choices that determine cross-encoder results."""

    model: str
    revision: str
    preprocessing_revision: str
    maximum_input_tokens: int

    def __post_init__(self) -> None:
        for name in ("model", "revision", "preprocessing_revision"):
            _require_text(getattr(self, name), name)
        _require_positive_integer(self.maximum_input_tokens, "maximum_input_tokens")


@dataclass(frozen=True)
class FusionSettings:
    """Rank-fusion settings; RRF parameters are provisional until calibration."""

    method: Literal["rrf"] = "rrf"
    rank_constant: int = 60

    def __post_init__(self) -> None:
        if self.method != "rrf":
            raise ValueError("only reciprocal-rank fusion is supported")
        _require_positive_integer(self.rank_constant, "rank_constant")


@dataclass(frozen=True)
class CandidateLimits:
    """Per-stage candidate bounds, with unused stages represented by null."""

    lexical_top_k: int | None = 50
    dense_top_k: int | None = 50
    fused_top_k: int | None = 50
    rerank_top_k: int | None = 10

    def __post_init__(self) -> None:
        for name in (
            "lexical_top_k",
            "dense_top_k",
            "fused_top_k",
            "rerank_top_k",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            limit = _require_positive_integer(value, name)
            if limit > DEFAULT_SEARCH_LIMITS.max_candidate_limit:
                raise ValueError(f"{name} exceeds the configured candidate maximum")


@dataclass(frozen=True)
class SelectionRules:
    """Paper/evidence result choices that change the visible ranked results."""

    paper_score_policy: Literal["strongest_passage"] = "strongest_passage"
    paper_support_limit: int = 3
    evidence_per_paper_limit: int = 3

    def __post_init__(self) -> None:
        if self.paper_score_policy != "strongest_passage":
            raise ValueError("unsupported paper score policy")
        for name in ("paper_support_limit", "evidence_per_paper_limit"):
            limit = _require_positive_integer(getattr(self, name), name)
            if limit > DEFAULT_SEARCH_LIMITS.max_per_paper_evidence_limit:
                raise ValueError(f"{name} exceeds the configured per-paper maximum")


@dataclass(frozen=True)
class RetrievalProfile:
    """Canonical retrieval choices bound to one exact snapshot chunk selection."""

    snapshot: SnapshotSelection
    lexical_index: LexicalIndexIdentity | None
    dense_index: DenseIndexIdentity | None
    reranker: RerankerIdentity | None = None
    fusion: FusionSettings | None = None
    candidate_limits: CandidateLimits = CandidateLimits()
    selection_rules: SelectionRules = SelectionRules()

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, SnapshotSelection):
            raise ValueError("snapshot must be a SnapshotSelection")
        if self.lexical_index is not None and not isinstance(
            self.lexical_index, LexicalIndexIdentity
        ):
            raise ValueError("lexical_index must be a LexicalIndexIdentity or null")
        if self.dense_index is not None and not isinstance(
            self.dense_index, DenseIndexIdentity
        ):
            raise ValueError("dense_index must be a DenseIndexIdentity or null")
        if self.lexical_index is None and self.dense_index is None:
            raise ValueError("a retrieval profile needs at least one search index")
        if self.reranker is not None and not isinstance(
            self.reranker, RerankerIdentity
        ):
            raise ValueError("reranker must be a RerankerIdentity or null")
        if self.fusion is not None and not isinstance(self.fusion, FusionSettings):
            raise ValueError("fusion must be FusionSettings or null")
        if not isinstance(self.candidate_limits, CandidateLimits):
            raise ValueError("candidate_limits must be CandidateLimits")
        if not isinstance(self.selection_rules, SelectionRules):
            raise ValueError("selection_rules must be SelectionRules")

        expected_candidate_presence = {
            "lexical_top_k": self.lexical_index is not None,
            "dense_top_k": self.dense_index is not None,
            "fused_top_k": self.fusion is not None,
            "rerank_top_k": self.reranker is not None,
        }
        for name, expected_present in expected_candidate_presence.items():
            if (getattr(self.candidate_limits, name) is not None) != expected_present:
                raise ValueError(f"{name} must match its configured retrieval stage")
        if self.fusion is not None and (
            self.lexical_index is None or self.dense_index is None
        ):
            raise ValueError("fusion requires lexical and dense indexes")
        if self.reranker is not None:
            rerank_limit = cast(int, self.candidate_limits.rerank_top_k)
            available_limit = max(
                self.candidate_limits.lexical_top_k or 0,
                self.candidate_limits.dense_top_k or 0,
                self.candidate_limits.fused_top_k or 0,
            )
            if rerank_limit > available_limit:
                raise ValueError("rerank_top_k cannot exceed its candidate pool")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _PROFILE_SCHEMA_VERSION,
            **_dataclass_dict(self),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RetrievalProfile:
        fields_by_name = {
            "schema_version",
            "snapshot",
            "lexical_index",
            "dense_index",
            "reranker",
            "fusion",
            "candidate_limits",
            "selection_rules",
        }
        _require_fields(data, fields_by_name, "retrieval profile")
        version = data["schema_version"]
        if isinstance(version, bool) or version != _PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported retrieval profile schema version")

        def optional_config(name: str, config_type: type[_ConfigT]) -> _ConfigT | None:
            raw = data[name]
            if raw is None:
                return None
            return _from_dataclass(config_type, _require_object(raw, name), name)

        snapshot = SnapshotSelection.from_dict(
            _require_object(data["snapshot"], "snapshot")
        )
        return cls(
            snapshot=snapshot,
            lexical_index=optional_config("lexical_index", LexicalIndexIdentity),
            dense_index=optional_config("dense_index", DenseIndexIdentity),
            reranker=optional_config("reranker", RerankerIdentity),
            fusion=optional_config("fusion", FusionSettings),
            candidate_limits=cast(
                CandidateLimits,
                optional_config("candidate_limits", CandidateLimits),
            ),
            selection_rules=cast(
                SelectionRules,
                optional_config("selection_rules", SelectionRules),
            ),
        )

    @property
    def profile_id(self) -> str:
        """Stable identity for compatibility; excludes code revision provenance."""
        return _canonical_identity(self.to_dict())


@dataclass(frozen=True)
class RetrievalProfileProvenance:
    """Build provenance stored separately from retrieval compatibility identity."""

    profile_id: str
    code_revision: str
    working_tree_dirty: bool

    def __post_init__(self) -> None:
        _require_sha256(self.profile_id, "profile_id")
        _require_text(self.code_revision, "code_revision")
        if not isinstance(self.working_tree_dirty, bool):
            raise ValueError("working_tree_dirty must be a boolean")

    def to_dict(self) -> dict[str, object]:
        return _dataclass_dict(self)
