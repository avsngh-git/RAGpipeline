"""Snapshot-bound BM25S index construction and non-text row manifests."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, cast
from uuid import UUID

import bm25s  # type: ignore[import-untyped]
import numpy as np

from research_platform.ingestion.evidence import EvidenceKind
from research_platform.ingestion.identity import (
    DocumentVersionKind,
    is_valid_paper_id,
)
from research_platform.ingestion.snapshot_selection import SnapshotSelection
from research_platform.search.contracts import (
    SearchFilters,
    SearchOperation,
    SearchResultStatus,
    _search_result_status,
    matches_filters,
)
from research_platform.search.lexical_analyzer import (
    ANALYZER_ID,
    ANALYZER_REVISION,
    NORMALIZATION_REVISION,
    tokenize_scientific_english,
)
from research_platform.search.profiles import LexicalIndexIdentity, RetrievalProfile

BM25S_VERSION = "0.3.11"
BM25S_IMPLEMENTATION_REVISION = (
    "0.3.11-k1.5-b0.75-delta0.5-lucene-idf-lucene-"
    "float32-int32-numpy-csc-numpy-auto-compile-true"
)
LEXICAL_INDEX_FORMAT_REVISION = "bm25s-csc-numpy-row-map-v2"
LEXICAL_INDEX_SCHEMA_VERSION = 2
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_EVIDENCE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
IndexRole = Literal["evidence", "paper"]


@dataclass(frozen=True)
class BM25ScoringSettings:
    """Parameters that determine BM25S scoring and sparse representation."""

    method: str = "lucene"
    idf_method: str = "lucene"
    k1: float = 1.5
    b: float = 0.75
    delta: float = 0.5
    dtype: str = "float32"
    int_dtype: str = "int32"
    backend: str = "numpy"
    csc_backend: str = "numpy"
    auto_compile: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


BM25_SCORING_SETTINGS = BM25ScoringSettings()

SCIENTIFIC_BM25_IDENTITY = LexicalIndexIdentity(
    implementation="bm25s",
    implementation_revision=BM25S_IMPLEMENTATION_REVISION,
    analyzer=ANALYZER_ID,
    analyzer_revision=ANALYZER_REVISION,
    normalization_revision=NORMALIZATION_REVISION,
    index_format_revision=LEXICAL_INDEX_FORMAT_REVISION,
)


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return _sha256(canonical.encode("utf-8"))


def _require_text_or_none(value: object, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be text or null")
    return value


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _has_active_filters(filters: SearchFilters) -> bool:
    return any(
        value is not None
        for value in (
            filters.year_from,
            filters.year_to,
            filters.paper_ids,
            filters.evidence_kinds,
            filters.document_version_kinds,
        )
    )


def _validate_filter_metadata(
    publication_year: object,
    evidence_kind: object,
    document_version_kind: object,
) -> None:
    if publication_year is not None and (
        isinstance(publication_year, bool)
        or not isinstance(publication_year, int)
        or publication_year < 0
    ):
        raise ValueError("publication_year must be a non-negative integer or null")
    valid_evidence_kinds = {
        "text",
        "table",
        "table_row_group",
        "caption",
        "figure",
        "equation",
    }
    if evidence_kind is not None and (
        not isinstance(evidence_kind, str) or evidence_kind not in valid_evidence_kinds
    ):
        raise ValueError("evidence_kind is unsupported")
    valid_document_kinds = {"published", "preprint", "other", "unknown"}
    if document_version_kind is not None and (
        not isinstance(document_version_kind, str)
        or document_version_kind not in valid_document_kinds
    ):
        raise ValueError("document_version_kind is unsupported")


@dataclass(frozen=True)
class EvidenceLexicalDocument:
    """One permission-checked selected chunk passed by the snapshot loader."""

    evidence_id: str
    paper_id: str
    document_id: UUID
    extraction_id: UUID
    source_artifact_sha256: str
    text: str
    publication_year: int | None = None
    evidence_kind: EvidenceKind | None = None
    document_version_kind: DocumentVersionKind | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, str) or not _STABLE_EVIDENCE_ID.fullmatch(
            self.evidence_id
        ):
            raise ValueError("evidence_id must be a stable SHA-256 identity")
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        if not isinstance(self.document_id, UUID) or not isinstance(
            self.extraction_id, UUID
        ):
            raise ValueError("document and extraction IDs must be UUIDs")
        _require_sha256(self.source_artifact_sha256, "source_artifact_sha256")
        if not isinstance(self.text, str):
            raise ValueError("evidence text must be a string")
        _validate_filter_metadata(
            self.publication_year,
            self.evidence_kind,
            self.document_version_kind,
        )


@dataclass(frozen=True)
class PaperLexicalDocument:
    """Paper-level title and optional reconstructed abstract fields."""

    paper_id: str
    title: str | None
    abstract: str | None

    def __post_init__(self) -> None:
        if not is_valid_paper_id(self.paper_id):
            raise ValueError("paper_id must be a canonical OpenAlex work ID")
        _require_text_or_none(self.title, "title")
        _require_text_or_none(self.abstract, "abstract")

    @property
    def index_text(self) -> str:
        fields = tuple(
            field.strip()
            for field in (self.title, self.abstract)
            if field is not None and field.strip()
        )
        return "\n\n".join(fields)


@dataclass(frozen=True)
class LexicalIndexRow:
    """Safe mapping from a BM25 row position to its authoritative record."""

    row: int
    stable_id: str
    paper_id: str
    content_sha256: str
    source_artifact_sha256: str | None = None
    document_id: str | None = None
    extraction_id: str | None = None
    title_sha256: str | None = None
    abstract_sha256: str | None = None
    has_title: bool | None = None
    has_abstract: bool | None = None
    publication_year: int | None = None
    evidence_kind: EvidenceKind | None = None
    document_version_kind: DocumentVersionKind | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> LexicalIndexRow:
        expected = {
            "row",
            "stable_id",
            "paper_id",
            "content_sha256",
            "source_artifact_sha256",
            "document_id",
            "extraction_id",
            "title_sha256",
            "abstract_sha256",
            "has_title",
            "has_abstract",
            "publication_year",
            "evidence_kind",
            "document_version_kind",
        }
        if set(value) != expected:
            raise ValueError("lexical row map fields are incomplete or unknown")
        row = value["row"]
        stable_id = value["stable_id"]
        paper_id = value["paper_id"]
        if isinstance(row, bool) or not isinstance(row, int) or row < 0:
            raise ValueError("lexical row position must be a non-negative integer")
        if not isinstance(stable_id, str) or not stable_id:
            raise ValueError("lexical stable ID must be non-empty text")
        if not isinstance(paper_id, str) or not is_valid_paper_id(paper_id):
            raise ValueError("lexical paper ID must be a canonical OpenAlex ID")
        content_sha256 = value["content_sha256"]
        if (
            not isinstance(content_sha256, str)
            or not content_sha256.startswith("sha256:")
            or _HEX_SHA256.fullmatch(content_sha256.removeprefix("sha256:")) is None
        ):
            raise ValueError("lexical content checksum is malformed")
        optional_text: dict[str, str | None] = {}
        for name in (
            "source_artifact_sha256",
            "document_id",
            "extraction_id",
            "title_sha256",
            "abstract_sha256",
        ):
            item = value[name]
            if item is not None and not isinstance(item, str):
                raise ValueError(f"lexical row {name} must be text or null")
            optional_text[name] = item
        for name in ("has_title", "has_abstract"):
            item = value[name]
            if item is not None and not isinstance(item, bool):
                raise ValueError(f"lexical row {name} must be boolean or null")
        publication_year = value["publication_year"]
        evidence_kind = value["evidence_kind"]
        document_version_kind = value["document_version_kind"]
        _validate_filter_metadata(
            publication_year, evidence_kind, document_version_kind
        )
        if optional_text["source_artifact_sha256"] is not None:
            _require_sha256(
                optional_text["source_artifact_sha256"], "source_artifact_sha256"
            )
        for name in ("title_sha256", "abstract_sha256"):
            item = optional_text[name]
            if item is not None and (
                not item.startswith("sha256:")
                or _HEX_SHA256.fullmatch(item.removeprefix("sha256:")) is None
            ):
                raise ValueError(f"lexical row {name} is malformed")
        for name in ("document_id", "extraction_id"):
            item = optional_text[name]
            if item is not None:
                try:
                    UUID(item)
                except ValueError:
                    raise ValueError(f"lexical row {name} is malformed") from None
        return cls(
            row=row,
            stable_id=stable_id,
            paper_id=paper_id,
            content_sha256=content_sha256,
            source_artifact_sha256=optional_text["source_artifact_sha256"],
            document_id=optional_text["document_id"],
            extraction_id=optional_text["extraction_id"],
            title_sha256=optional_text["title_sha256"],
            abstract_sha256=optional_text["abstract_sha256"],
            has_title=cast(bool | None, value["has_title"]),
            has_abstract=cast(bool | None, value["has_abstract"]),
            publication_year=cast(int | None, publication_year),
            evidence_kind=cast(EvidenceKind | None, evidence_kind),
            document_version_kind=cast(
                DocumentVersionKind | None, document_version_kind
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "row": self.row,
            "stable_id": self.stable_id,
            "paper_id": self.paper_id,
            "content_sha256": self.content_sha256,
            "source_artifact_sha256": self.source_artifact_sha256,
            "document_id": self.document_id,
            "extraction_id": self.extraction_id,
            "title_sha256": self.title_sha256,
            "abstract_sha256": self.abstract_sha256,
            "has_title": self.has_title,
            "has_abstract": self.has_abstract,
            "publication_year": self.publication_year,
            "evidence_kind": self.evidence_kind,
            "document_version_kind": self.document_version_kind,
        }


@dataclass(frozen=True)
class LexicalIndexManifest:
    """Compatibility identity and row-map fingerprint for one BM25 corpus."""

    role: IndexRole
    snapshot_status: Literal["draft", "finalized"]
    snapshot: SnapshotSelection
    profile_id: str
    lexical_index_id: str
    row_count: int
    candidate_limit: int
    empty_token_row_count: int
    duplicate_content_row_count: int
    row_map_sha256: str
    scoring: BM25ScoringSettings

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": LEXICAL_INDEX_SCHEMA_VERSION,
            "role": self.role,
            "snapshot_status": self.snapshot_status,
            "snapshot": self.snapshot.to_dict(),
            "profile_id": self.profile_id,
            "lexical_index_id": self.lexical_index_id,
            "analyzer": {
                "id": ANALYZER_ID,
                "revision": ANALYZER_REVISION,
                "normalization_revision": NORMALIZATION_REVISION,
            },
            "scoring": self.scoring.to_dict(),
            "row_count": self.row_count,
            "candidate_limit": self.candidate_limit,
            "empty_token_row_count": self.empty_token_row_count,
            "duplicate_content_row_count": self.duplicate_content_row_count,
            "row_map_sha256": self.row_map_sha256,
        }


@dataclass(frozen=True)
class BuiltLexicalIndex:
    """In-memory BM25S index plus its profile and source-text-free row map."""

    profile: RetrievalProfile
    manifest: LexicalIndexManifest
    rows: tuple[LexicalIndexRow, ...]
    engine: Any

    def to_manifest_dict(self) -> dict[str, object]:
        return self.manifest.to_dict()

    def to_row_map(self) -> list[dict[str, object]]:
        return [row.to_dict() for row in self.rows]


def _new_engine(tokenized_documents: list[list[str]]) -> tuple[Any, int]:
    if bm25s.__version__ != BM25S_VERSION:
        raise RuntimeError(
            f"BM25S {BM25S_VERSION} is required; found {bm25s.__version__}"
        )
    scoring = BM25_SCORING_SETTINGS
    engine = bm25s.BM25(
        k1=scoring.k1,
        b=scoring.b,
        delta=scoring.delta,
        method=scoring.method,
        idf_method=scoring.idf_method,
        dtype=scoring.dtype,
        int_dtype=scoring.int_dtype,
        backend=scoring.backend,
        csc_backend=scoring.csc_backend,
        auto_compile=scoring.auto_compile,
    )
    engine.index(
        tokenized_documents,
        create_empty_token=True,
        show_progress=False,
    )
    # BM25S otherwise retains input data and writes it as corpus.jsonl on save.
    engine.corpus = None
    return engine, sum(not tokens for tokens in tokenized_documents)


def _validate_profile(profile: RetrievalProfile) -> None:
    if profile.lexical_index != SCIENTIFIC_BM25_IDENTITY:
        raise ValueError("profile does not select this BM25S analyzer and scoring")


def _make_artifact(
    *,
    role: IndexRole,
    profile: RetrievalProfile,
    rows: list[LexicalIndexRow],
    texts: list[str],
    snapshot_status: Literal["draft", "finalized"],
) -> BuiltLexicalIndex:
    if len(rows) != len(texts) or not rows:
        raise ValueError("a lexical index needs aligned, non-empty document rows")
    row_payload = [row.to_dict() for row in rows]
    tokenized = [list(tokenize_scientific_english(text)) for text in texts]
    engine, empty_count = _new_engine(tokenized)
    content_counts: dict[str, int] = {}
    for row in rows:
        content_counts[row.content_sha256] = (
            content_counts.get(row.content_sha256, 0) + 1
        )
    duplicate_rows = sum(count - 1 for count in content_counts.values() if count > 1)
    candidate_limit = profile.candidate_limits.lexical_top_k
    if candidate_limit is None:
        raise ValueError("lexical profile is missing its candidate limit")
    if snapshot_status not in {"draft", "finalized"}:
        raise ValueError("snapshot status must be draft or finalized")
    manifest = LexicalIndexManifest(
        role=role,
        snapshot_status=snapshot_status,
        snapshot=profile.snapshot,
        profile_id=profile.profile_id,
        lexical_index_id=SCIENTIFIC_BM25_IDENTITY.configuration_id,
        row_count=len(rows),
        candidate_limit=candidate_limit,
        empty_token_row_count=empty_count,
        duplicate_content_row_count=duplicate_rows,
        row_map_sha256=_canonical_sha256(row_payload),
        scoring=BM25_SCORING_SETTINGS,
    )
    return BuiltLexicalIndex(
        profile=profile, manifest=manifest, rows=tuple(rows), engine=engine
    )


def build_evidence_index(
    documents: tuple[EvidenceLexicalDocument, ...],
    profile: RetrievalProfile,
    *,
    snapshot_status: Literal["draft", "finalized"] = "draft",
) -> BuiltLexicalIndex:
    """Build a separate evidence BM25 index in stable evidence-ID order."""
    _validate_profile(profile)
    if not documents:
        raise ValueError("evidence index input must not be empty")
    by_id = {document.evidence_id: document for document in documents}
    if len(by_id) != len(documents):
        raise ValueError("duplicate evidence IDs are not allowed")
    ordered = [by_id[key] for key in sorted(by_id)]
    rows = [
        LexicalIndexRow(
            row=row,
            stable_id=document.evidence_id,
            paper_id=document.paper_id,
            content_sha256=_sha256(document.text.encode("utf-8")),
            source_artifact_sha256=document.source_artifact_sha256,
            document_id=str(document.document_id),
            extraction_id=str(document.extraction_id),
            publication_year=document.publication_year,
            evidence_kind=document.evidence_kind,
            document_version_kind=document.document_version_kind,
        )
        for row, document in enumerate(ordered)
    ]
    return _make_artifact(
        role="evidence",
        profile=profile,
        rows=rows,
        texts=[document.text for document in ordered],
        snapshot_status=snapshot_status,
    )


def build_paper_index(
    documents: tuple[PaperLexicalDocument, ...],
    profile: RetrievalProfile,
    *,
    snapshot_status: Literal["draft", "finalized"] = "draft",
) -> BuiltLexicalIndex:
    """Build a distinct paper index from available title and abstract text."""
    _validate_profile(profile)
    if not documents:
        raise ValueError("paper index input must not be empty")
    by_id = {document.paper_id: document for document in documents}
    if len(by_id) != len(documents):
        raise ValueError("duplicate paper IDs are not allowed")
    ordered = [by_id[key] for key in sorted(by_id)]
    rows: list[LexicalIndexRow] = []
    texts: list[str] = []
    for row, document in enumerate(ordered):
        index_text = document.index_text
        title = document.title.strip() if document.title is not None else ""
        abstract = document.abstract.strip() if document.abstract is not None else ""
        rows.append(
            LexicalIndexRow(
                row=row,
                stable_id=document.paper_id,
                paper_id=document.paper_id,
                content_sha256=_sha256(index_text.encode("utf-8")),
                title_sha256=_sha256(title.encode("utf-8")) if title else None,
                abstract_sha256=_sha256(abstract.encode("utf-8")) if abstract else None,
                has_title=bool(title),
                has_abstract=bool(abstract),
            )
        )
        texts.append(index_text)
    return _make_artifact(
        role="paper",
        profile=profile,
        rows=rows,
        texts=texts,
        snapshot_status=snapshot_status,
    )


@dataclass(frozen=True)
class LexicalHit:
    """One positive-score lexical result mapped to its authoritative ID."""

    stable_id: str
    paper_id: str
    row: int
    score: float


@dataclass(frozen=True)
class LexicalSearchResult:
    """Exact eligibility and positive-match counts for one bounded lexical query."""

    hits: tuple[LexicalHit, ...]
    available_count: int
    eligible_count: int
    limit: int
    truncated: bool
    applied_filters: SearchFilters = SearchFilters()

    @property
    def result_status(self) -> SearchResultStatus:
        """Distinguish empty filter scope from eligible records with no lexical hit."""
        return _search_result_status(self.eligible_count, len(self.hits))

    def __post_init__(self) -> None:
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or self.limit <= 0
        ):
            raise ValueError("limit must be a positive integer")
        if (
            isinstance(self.available_count, bool)
            or not isinstance(self.available_count, int)
            or self.available_count < 0
        ):
            raise ValueError("available_count must be a non-negative integer")
        if (
            isinstance(self.eligible_count, bool)
            or not isinstance(self.eligible_count, int)
            or self.eligible_count < 0
        ):
            raise ValueError("eligible_count must be a non-negative integer")
        if not isinstance(self.truncated, bool):
            raise ValueError("truncated must be boolean")
        if not isinstance(self.applied_filters, SearchFilters):
            raise ValueError("applied_filters must be SearchFilters")
        if self.available_count < len(self.hits):
            raise ValueError("available_count cannot be smaller than returned hits")
        if self.available_count > self.eligible_count:
            raise ValueError("positive matches cannot exceed eligible records")
        if len(self.hits) > self.limit:
            raise ValueError("returned lexical hits exceed the query limit")
        if self.truncated != (self.available_count > self.limit):
            raise ValueError("truncated must match the available hit count and limit")


class LexicalRetriever:
    """Score an index, applying its authoritative eligible row IDs before top-k."""

    def __init__(self, index: BuiltLexicalIndex) -> None:
        self._index = index
        self._row_by_id = {row.stable_id: row for row in index.rows}
        if len(self._row_by_id) != len(index.rows):
            raise ValueError("lexical row map contains duplicate stable IDs")

    @property
    def profile(self) -> RetrievalProfile:
        """The exact retrieval profile used to build this lexical index."""
        return self._index.profile

    @property
    def manifest(self) -> LexicalIndexManifest:
        """The immutable role, snapshot and candidate bound for this index."""
        return self._index.manifest

    def search(
        self,
        query: str,
        *,
        eligible_ids: Collection[str] | None = None,
        limit: int = 10,
        filters: SearchFilters = SearchFilters(),
    ) -> tuple[LexicalHit, ...]:
        """Return positive matches from the eligible set with stable score ties."""
        return self.search_with_stats(
            query, eligible_ids=eligible_ids, limit=limit, filters=filters
        ).hits

    def search_with_stats(
        self,
        query: str,
        *,
        eligible_ids: Collection[str] | None = None,
        limit: int = 10,
        filters: SearchFilters = SearchFilters(),
    ) -> LexicalSearchResult:
        """Return bounded hits plus the exact positive-match count."""
        if not isinstance(query, str):
            raise TypeError("query must be text")
        if not isinstance(filters, SearchFilters):
            raise ValueError("filters must be SearchFilters")
        filters.validate_for(SearchOperation.EVIDENCE_SEARCH)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        if limit > self._index.manifest.candidate_limit:
            raise ValueError("limit exceeds the profile lexical candidate limit")
        if eligible_ids is None:
            eligible_rows = set(range(len(self._index.rows)))
        else:
            if any(not isinstance(stable_id, str) for stable_id in eligible_ids):
                raise ValueError("eligible IDs must be strings")
            requested_ids = set(eligible_ids)
            unknown_ids = requested_ids.difference(self._row_by_id)
            if unknown_ids:
                raise ValueError("eligible IDs are outside this lexical index")
            eligible_rows = {
                self._row_by_id[stable_id].row for stable_id in requested_ids
            }

        if _has_active_filters(filters):
            eligible_rows = {
                row.row
                for row in self._index.rows
                if row.row in eligible_rows
                and matches_filters(
                    filters,
                    operation=SearchOperation.EVIDENCE_SEARCH,
                    paper_id=row.paper_id,
                    publication_year=row.publication_year,
                    evidence_kind=row.evidence_kind,
                    document_version_kind=row.document_version_kind,
                )
            }
        eligible_count = len(eligible_rows)
        tokens = tokenize_scientific_english(query)
        if not eligible_rows or not tokens:
            return LexicalSearchResult(
                hits=(),
                available_count=0,
                eligible_count=eligible_count,
                limit=limit,
                truncated=False,
                applied_filters=filters,
            )

        score_array = np.asarray(self._index.engine.get_scores(list(tokens)))
        if score_array.shape != (len(self._index.rows),):
            raise RuntimeError("BM25S score vector does not match the row map")
        scored: list[LexicalHit] = []
        for row_index in eligible_rows:
            score = float(score_array[row_index])
            if not math.isfinite(score):
                raise RuntimeError("BM25S returned a non-finite score")
            if score > 0.0:
                row = self._index.rows[row_index]
                scored.append(
                    LexicalHit(
                        stable_id=row.stable_id,
                        paper_id=row.paper_id,
                        row=row.row,
                        score=score,
                    )
                )
        scored.sort(key=lambda hit: (-hit.score, hit.stable_id))
        available_count = len(scored)
        hits = tuple(scored[:limit])
        return LexicalSearchResult(
            hits=hits,
            available_count=available_count,
            eligible_count=eligible_count,
            limit=limit,
            truncated=available_count > limit,
            applied_filters=filters,
        )
