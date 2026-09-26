"""Strict loader for versioned, source-grounded calibration datasets."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

import tomllib

from research_platform.ingestion.evidence import EvidenceKind
from research_platform.ingestion.identity import (
    DocumentVersionKind,
    is_valid_paper_id,
)
from research_platform.search.contracts import SearchFilters

_DATASET_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_RECORD_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CATEGORIES = {
    "discovery",
    "specific_evidence",
    "table_result",
    "cross_paper_comparison",
    "filters",
    "missing_evidence",
}
_SOURCE_CHECKS = {
    "original_pdf_visual",
    "publisher_fulltext",
    "original_pdf_text_crosschecked",
}
_SPLITS = {"development", "held_out"}


class CalibrationLoadError(ValueError):
    """The calibration dataset is malformed or internally inconsistent."""


@dataclass(frozen=True)
class CalibrationSourceDocument:
    """Exact source artifact and extraction identity for one paper version."""

    document_id: UUID
    paper_id: str
    extraction_id: UUID
    pdf_sha256: str


@dataclass(frozen=True)
class CalibrationSourceAnchor:
    """A PDF-grounded prose passage or table region independent of chunking."""

    id: str
    document_id: UUID
    page_index_zero_based: int
    region_type: Literal["prose", "table"]
    locator: str
    source_check: str
    table_label: str | None = None
    row_context: str | None = None
    column_context: str | None = None
    interpretive_context: str | None = None


@dataclass(frozen=True)
class CalibrationQuery:
    """One canonical query or paraphrase within a family."""

    id: str
    role: Literal["canonical", "paraphrase"]
    text: str


@dataclass(frozen=True)
class PaperJudgment:
    """Graded paper relevance for one family."""

    paper_id: str
    label: int
    rationale: str


@dataclass(frozen=True)
class EvidenceJudgment:
    """Graded relevance for one canonical source anchor."""

    paper_id: str
    source_anchor_id: str
    label: int
    rationale: str


@dataclass(frozen=True)
class EvidenceRequirementGroup:
    """Evidence pieces that must all be retrieved; each piece has alternatives."""

    id: str
    required_pieces: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class QuestionFamily:
    """One information need, its split, filters, judgments, and evidence groups."""

    id: str
    split: Literal["development", "held_out"]
    categories: tuple[str, ...]
    reviewer_status: Literal["assistant_reviewed"]
    reviewed_on: date
    filters: SearchFilters
    unsupported: bool
    requires_evidence: bool
    queries: tuple[CalibrationQuery, ...]
    paper_judgments: tuple[PaperJudgment, ...]
    evidence_judgments: tuple[EvidenceJudgment, ...]
    evidence_groups: tuple[EvidenceRequirementGroup, ...]


@dataclass(frozen=True)
class CalibrationDataset:
    """Validated, immutable view of a calibration TOML file."""

    schema_version: int
    dataset_id: str
    dataset_kind: Literal["calibration"]
    snapshot_id: UUID
    split_policy_id: str
    source_documents: tuple[CalibrationSourceDocument, ...]
    source_anchors: tuple[CalibrationSourceAnchor, ...]
    families: tuple[QuestionFamily, ...]


def load_calibration(path: str | Path) -> CalibrationDataset:
    """Load and validate a TOML calibration dataset from disk."""
    source_path = Path(path)
    try:
        contents = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CalibrationLoadError(
            f"cannot read calibration file {source_path}"
        ) from exc
    try:
        return parse_calibration(contents)
    except CalibrationLoadError as exc:
        raise CalibrationLoadError(f"{source_path}: {exc}") from exc


def parse_calibration(contents: str) -> CalibrationDataset:
    """Parse TOML text and reject malformed fields and invalid references."""
    if not isinstance(contents, str):
        raise CalibrationLoadError("TOML contents must be text")
    try:
        raw = tomllib.loads(contents)
    except tomllib.TOMLDecodeError as exc:
        raise CalibrationLoadError(f"invalid TOML: {exc}") from exc

    _require_fields(
        raw,
        required={
            "schema_version",
            "dataset_id",
            "dataset_kind",
            "snapshot_id",
            "split_policy_id",
            "source_documents",
            "source_anchors",
            "families",
        },
        path="dataset",
    )
    schema_version = _integer(raw["schema_version"], "schema_version", minimum=1)
    if schema_version != 1:
        raise CalibrationLoadError("schema_version must be 1")
    dataset_id = _string(raw["dataset_id"], "dataset_id")
    if not _DATASET_ID.fullmatch(dataset_id):
        raise CalibrationLoadError("dataset_id must be a lowercase hyphenated ID")
    if raw["dataset_kind"] != "calibration":
        raise CalibrationLoadError('dataset_kind must be "calibration"')
    snapshot_id = _uuid(raw["snapshot_id"], "snapshot_id")
    split_policy_id = _string(raw["split_policy_id"], "split_policy_id")
    if not _RECORD_ID.fullmatch(split_policy_id):
        raise CalibrationLoadError("split_policy_id must be a lowercase hyphenated ID")

    raw_documents = _records(raw["source_documents"], "source_documents")
    documents = tuple(
        _parse_source_document(record, index)
        for index, record in enumerate(raw_documents)
    )
    _unique((str(record.document_id) for record in documents), "source document ID")
    _unique((str(record.extraction_id) for record in documents), "extraction ID")
    documents_by_id = {record.document_id: record for record in documents}
    if not documents:
        raise CalibrationLoadError("source_documents must not be empty")

    raw_anchors = _records(raw["source_anchors"], "source_anchors")
    anchors = tuple(
        _parse_source_anchor(record, index, documents_by_id)
        for index, record in enumerate(raw_anchors)
    )
    _unique((record.id for record in anchors), "source anchor ID")
    anchors_by_id = {record.id: record for record in anchors}
    if not anchors:
        raise CalibrationLoadError("source_anchors must not be empty")

    raw_families = _records(raw["families"], "families")
    _validate_family_splits(raw_families)
    families = tuple(
        _parse_family(record, index, documents_by_id, anchors_by_id)
        for index, record in enumerate(raw_families)
    )
    _unique((record.id for record in families), "family ID")
    if not families:
        raise CalibrationLoadError("families must not be empty")
    if any(family.split != "development" for family in families):
        raise CalibrationLoadError(
            "calibration families must all use the development split"
        )
    _unique((query.id for family in families for query in family.queries), "query ID")
    all_group_ids = (
        group.id for family in families for group in family.evidence_groups
    )
    _unique(all_group_ids, "evidence group ID")

    return CalibrationDataset(
        schema_version=schema_version,
        dataset_id=dataset_id,
        dataset_kind="calibration",
        snapshot_id=snapshot_id,
        split_policy_id=split_policy_id,
        source_documents=documents,
        source_anchors=anchors,
        families=families,
    )


def _parse_source_document(raw: object, index: int) -> CalibrationSourceDocument:
    path = f"source_documents[{index}]"
    record = _mapping(
        raw,
        path,
        required={"document_id", "paper_id", "extraction_id", "pdf_sha256"},
    )
    paper_id = _string(record["paper_id"], f"{path}.paper_id")
    if not is_valid_paper_id(paper_id):
        raise CalibrationLoadError(f"{path}.paper_id must be a canonical OpenAlex ID")
    pdf_sha256 = _string(record["pdf_sha256"], f"{path}.pdf_sha256")
    if not _SHA256.fullmatch(pdf_sha256):
        raise CalibrationLoadError(f"{path}.pdf_sha256 must be 64 lowercase hex digits")
    return CalibrationSourceDocument(
        document_id=_uuid(record["document_id"], f"{path}.document_id"),
        paper_id=paper_id,
        extraction_id=_uuid(record["extraction_id"], f"{path}.extraction_id"),
        pdf_sha256=pdf_sha256,
    )


def _parse_source_anchor(
    raw: object,
    index: int,
    documents_by_id: dict[UUID, CalibrationSourceDocument],
) -> CalibrationSourceAnchor:
    path = f"source_anchors[{index}]"
    record = _mapping(
        raw,
        path,
        required={
            "id",
            "document_id",
            "page_index_zero_based",
            "region_type",
            "locator",
            "source_check",
        },
        optional={
            "table_label",
            "row_context",
            "column_context",
            "interpretive_context",
        },
    )
    anchor_id = _string(record["id"], f"{path}.id")
    if not _RECORD_ID.fullmatch(anchor_id):
        raise CalibrationLoadError(f"{path}.id must be a lowercase hyphenated ID")
    document_id = _uuid(record["document_id"], f"{path}.document_id")
    if document_id not in documents_by_id:
        raise CalibrationLoadError(f"{path}.document_id references an unknown document")
    page = _integer(record["page_index_zero_based"], f"{path}.page_index_zero_based")
    region_type = _string(record["region_type"], f"{path}.region_type")
    if region_type not in {"prose", "table"}:
        raise CalibrationLoadError(f"{path}.region_type must be prose or table")
    locator = _string(record["locator"], f"{path}.locator")
    source_check = _string(record["source_check"], f"{path}.source_check")
    if source_check not in _SOURCE_CHECKS:
        raise CalibrationLoadError(f"{path}.source_check is not a supported check")
    table_fields = ("table_label", "row_context", "column_context")
    optional_text: dict[str, str | None] = {}
    for field in (*table_fields, "interpretive_context"):
        value = record.get(field)
        optional_text[field] = (
            _string(value, f"{path}.{field}") if value is not None else None
        )
    if region_type == "table":
        if any(optional_text[field] is None for field in table_fields):
            raise CalibrationLoadError(
                f"{path} table anchors require label, row context, and column context"
            )
    elif any(optional_text[field] is not None for field in table_fields):
        raise CalibrationLoadError(f"{path} prose anchors cannot contain table fields")
    return CalibrationSourceAnchor(
        id=anchor_id,
        document_id=document_id,
        page_index_zero_based=page,
        region_type=cast(Literal["prose", "table"], region_type),
        locator=locator,
        source_check=source_check,
        table_label=optional_text["table_label"],
        row_context=optional_text["row_context"],
        column_context=optional_text["column_context"],
        interpretive_context=optional_text["interpretive_context"],
    )


def _parse_family(
    raw: object,
    index: int,
    documents_by_id: dict[UUID, CalibrationSourceDocument],
    anchors_by_id: dict[str, CalibrationSourceAnchor],
) -> QuestionFamily:
    path = f"families[{index}]"
    record = _mapping(
        raw,
        path,
        required={
            "id",
            "split",
            "categories",
            "reviewer_status",
            "reviewed_on",
            "filters",
            "unsupported",
            "requires_evidence",
            "queries",
            "paper_judgments",
            "evidence_judgments",
        },
        optional={"evidence_groups"},
    )
    family_id = _string(record["id"], f"{path}.id")
    if not _RECORD_ID.fullmatch(family_id):
        raise CalibrationLoadError(f"{path}.id must be a lowercase hyphenated ID")
    split = _string(record["split"], f"{path}.split")
    if split not in _SPLITS:
        raise CalibrationLoadError(f"{path}.split must be development or held_out")
    categories = _string_tuple(record["categories"], f"{path}.categories")
    if not categories:
        raise CalibrationLoadError(f"{path}.categories must not be empty")
    if len(set(categories)) != len(categories) or any(
        category not in _CATEGORIES for category in categories
    ):
        raise CalibrationLoadError(
            f"{path}.categories contains duplicate or unknown values"
        )
    if record["reviewer_status"] != "assistant_reviewed":
        raise CalibrationLoadError(f"{path}.reviewer_status must be assistant_reviewed")
    reviewed_on = record["reviewed_on"]
    if isinstance(reviewed_on, str):
        try:
            reviewed_on = date.fromisoformat(reviewed_on)
        except ValueError as exc:
            raise CalibrationLoadError(
                f"{path}.reviewed_on must be an ISO date"
            ) from exc
    if not isinstance(reviewed_on, date):
        raise CalibrationLoadError(f"{path}.reviewed_on must be an ISO date")
    filters = _parse_filters(record["filters"], f"{path}.filters")
    unsupported = _boolean(record["unsupported"], f"{path}.unsupported")
    requires_evidence = _boolean(
        record["requires_evidence"], f"{path}.requires_evidence"
    )

    queries = tuple(
        _parse_query(item, f"{path}.queries[{query_index}]")
        for query_index, item in enumerate(
            _records(record["queries"], f"{path}.queries")
        )
    )
    if not queries:
        raise CalibrationLoadError(f"{path}.queries must not be empty")
    _unique((query.id for query in queries), f"query ID in {family_id}")
    if sum(query.role == "canonical" for query in queries) != 1:
        raise CalibrationLoadError(
            f"{path}.queries must contain exactly one canonical query"
        )

    paper_judgments = tuple(
        _parse_paper_judgment(item, f"{path}.paper_judgments[{judgment_index}]")
        for judgment_index, item in enumerate(
            _records(record["paper_judgments"], f"{path}.paper_judgments")
        )
    )
    if not paper_judgments:
        raise CalibrationLoadError(f"{path}.paper_judgments must not be empty")
    _unique(
        (judgment.paper_id for judgment in paper_judgments),
        f"paper judgment in {family_id}",
    )
    known_papers = {document.paper_id for document in documents_by_id.values()}
    for judgment in paper_judgments:
        if judgment.paper_id not in known_papers:
            raise CalibrationLoadError(
                f"{path}.paper_judgments references a paper absent from source_documents"
            )

    evidence_judgments = tuple(
        _parse_evidence_judgment(
            item,
            f"{path}.evidence_judgments[{judgment_index}]",
            anchors_by_id,
            documents_by_id,
        )
        for judgment_index, item in enumerate(
            _records(record["evidence_judgments"], f"{path}.evidence_judgments")
        )
    )
    evidence_keys = (
        (judgment.paper_id, judgment.source_anchor_id)
        for judgment in evidence_judgments
    )
    _unique(evidence_keys, f"evidence judgment in {family_id}")
    paper_judgment_ids = {judgment.paper_id for judgment in paper_judgments}
    for evidence_judgment in evidence_judgments:
        if evidence_judgment.paper_id not in paper_judgment_ids:
            raise CalibrationLoadError(
                f"{path}.evidence_judgments requires a paper judgment for its paper"
            )

    evidence_groups = tuple(
        _parse_evidence_group(
            item,
            f"{path}.evidence_groups[{group_index}]",
            anchors_by_id,
            evidence_judgments,
        )
        for group_index, item in enumerate(
            _records(record.get("evidence_groups", []), f"{path}.evidence_groups")
        )
    )
    _unique((group.id for group in evidence_groups), f"evidence group in {family_id}")
    if unsupported:
        if requires_evidence or evidence_groups:
            raise CalibrationLoadError(
                f"{path} unsupported families cannot require positive evidence groups"
            )
        if any(judgment.label == 2 for judgment in paper_judgments) or any(
            judgment.label == 2 for judgment in evidence_judgments
        ):
            raise CalibrationLoadError(
                f"{path} unsupported families cannot contain label-2 judgments"
            )
    elif requires_evidence and not evidence_groups:
        raise CalibrationLoadError(
            f"{path} requires evidence but has no evidence requirement groups"
        )
    elif not requires_evidence and evidence_groups:
        raise CalibrationLoadError(
            f"{path} has evidence groups but does not require evidence"
        )
    return QuestionFamily(
        id=family_id,
        split=cast(Literal["development", "held_out"], split),
        categories=categories,
        reviewer_status="assistant_reviewed",
        reviewed_on=reviewed_on,
        filters=filters,
        unsupported=unsupported,
        requires_evidence=requires_evidence,
        queries=queries,
        paper_judgments=paper_judgments,
        evidence_judgments=evidence_judgments,
        evidence_groups=evidence_groups,
    )


def _parse_query(raw: object, path: str) -> CalibrationQuery:
    record = _mapping(raw, path, required={"id", "role", "text"})
    query_id = _string(record["id"], f"{path}.id")
    if not _RECORD_ID.fullmatch(query_id):
        raise CalibrationLoadError(f"{path}.id must be a lowercase hyphenated ID")
    role = _string(record["role"], f"{path}.role")
    if role not in {"canonical", "paraphrase"}:
        raise CalibrationLoadError(f"{path}.role must be canonical or paraphrase")
    return CalibrationQuery(
        id=query_id,
        role=cast(Literal["canonical", "paraphrase"], role),
        text=_string(record["text"], f"{path}.text"),
    )


def _parse_paper_judgment(raw: object, path: str) -> PaperJudgment:
    record = _mapping(raw, path, required={"paper_id", "label", "rationale"})
    return PaperJudgment(
        paper_id=_paper_id(record["paper_id"], f"{path}.paper_id"),
        label=_label(record["label"], f"{path}.label"),
        rationale=_string(record["rationale"], f"{path}.rationale"),
    )


def _parse_evidence_judgment(
    raw: object,
    path: str,
    anchors_by_id: dict[str, CalibrationSourceAnchor],
    documents_by_id: dict[UUID, CalibrationSourceDocument],
) -> EvidenceJudgment:
    record = _mapping(
        raw, path, required={"paper_id", "source_anchor_id", "label", "rationale"}
    )
    paper_id = _paper_id(record["paper_id"], f"{path}.paper_id")
    anchor_id = _string(record["source_anchor_id"], f"{path}.source_anchor_id")
    anchor = anchors_by_id.get(anchor_id)
    if anchor is None:
        raise CalibrationLoadError(
            f"{path}.source_anchor_id references an unknown anchor"
        )
    if documents_by_id[anchor.document_id].paper_id != paper_id:
        raise CalibrationLoadError(
            f"{path}.paper_id does not match the source anchor's document"
        )
    return EvidenceJudgment(
        paper_id=paper_id,
        source_anchor_id=anchor_id,
        label=_label(record["label"], f"{path}.label"),
        rationale=_string(record["rationale"], f"{path}.rationale"),
    )


def _parse_evidence_group(
    raw: object,
    path: str,
    anchors_by_id: dict[str, CalibrationSourceAnchor],
    judgments: tuple[EvidenceJudgment, ...],
) -> EvidenceRequirementGroup:
    record = _mapping(raw, path, required={"id", "required_pieces"})
    group_id = _string(record["id"], f"{path}.id")
    if not _RECORD_ID.fullmatch(group_id):
        raise CalibrationLoadError(f"{path}.id must be a lowercase hyphenated ID")
    raw_pieces = record["required_pieces"]
    if not isinstance(raw_pieces, list) or not raw_pieces:
        raise CalibrationLoadError(f"{path}.required_pieces must not be empty")
    positive_judgments = {
        judgment.source_anchor_id for judgment in judgments if judgment.label == 2
    }
    pieces: list[tuple[str, ...]] = []
    for piece_index, raw_piece in enumerate(raw_pieces):
        piece_path = f"{path}.required_pieces[{piece_index}]"
        alternatives = _string_tuple(raw_piece, piece_path)
        if not alternatives:
            raise CalibrationLoadError(f"{piece_path} must not be empty")
        if len(set(alternatives)) != len(alternatives):
            raise CalibrationLoadError(f"{piece_path} contains duplicate alternatives")
        for anchor_id in alternatives:
            if anchor_id not in anchors_by_id:
                raise CalibrationLoadError(
                    f"{piece_path} references unknown source anchor {anchor_id}"
                )
            if anchor_id not in positive_judgments:
                raise CalibrationLoadError(
                    f"{piece_path} alternatives must have label-2 evidence judgments"
                )
        pieces.append(alternatives)
    return EvidenceRequirementGroup(id=group_id, required_pieces=tuple(pieces))


def _parse_filters(raw: object, path: str) -> SearchFilters:
    record = _mapping(
        raw,
        path,
        required=set(),
        optional={
            "year_from",
            "year_to",
            "paper_ids",
            "evidence_kinds",
            "document_version_kinds",
        },
    )
    year_from = (
        _integer(record["year_from"], f"{path}.year_from")
        if "year_from" in record
        else None
    )
    year_to = (
        _integer(record["year_to"], f"{path}.year_to") if "year_to" in record else None
    )
    paper_ids = (
        _string_tuple(record["paper_ids"], f"{path}.paper_ids")
        if "paper_ids" in record
        else None
    )
    evidence_kinds = (
        cast(
            tuple[EvidenceKind, ...],
            _string_tuple(record["evidence_kinds"], f"{path}.evidence_kinds"),
        )
        if "evidence_kinds" in record
        else None
    )
    document_version_kinds = (
        cast(
            tuple[DocumentVersionKind, ...],
            _string_tuple(
                record["document_version_kinds"], f"{path}.document_version_kinds"
            ),
        )
        if "document_version_kinds" in record
        else None
    )
    try:
        return SearchFilters(
            year_from=year_from,
            year_to=year_to,
            paper_ids=paper_ids,
            evidence_kinds=evidence_kinds,
            document_version_kinds=document_version_kinds,
        )
    except ValueError as exc:
        raise CalibrationLoadError(f"{path}: {exc}") from exc


def _validate_family_splits(records: list[dict[str, object]]) -> None:
    splits_by_id: dict[str, set[str]] = {}
    for index, record in enumerate(records):
        if "id" not in record or "split" not in record:
            raise CalibrationLoadError(
                f"families[{index}] must include id and split for split validation"
            )
        family_id = _string(record["id"], f"families[{index}].id")
        split = _string(record["split"], f"families[{index}].split")
        splits_by_id.setdefault(family_id, set()).add(split)
    overlaps = sorted(
        family_id for family_id, splits in splits_by_id.items() if len(splits) > 1
    )
    if overlaps:
        raise CalibrationLoadError(
            f"question families must not overlap splits: {', '.join(overlaps)}"
        )


def _require_fields(
    record: dict[str, object], *, required: set[str], path: str
) -> None:
    missing = sorted(required - record.keys())
    unknown = sorted(record.keys() - required)
    if missing:
        raise CalibrationLoadError(f"{path} is missing fields: {', '.join(missing)}")
    if unknown:
        raise CalibrationLoadError(f"{path} has unknown fields: {', '.join(unknown)}")


def _mapping(
    raw: object,
    path: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, object]:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise CalibrationLoadError(f"{path} must be a TOML table")
    optional_fields = optional or set()
    missing = sorted(required - raw.keys())
    unknown = sorted(raw.keys() - required - optional_fields)
    if missing:
        raise CalibrationLoadError(f"{path} is missing fields: {', '.join(missing)}")
    if unknown:
        raise CalibrationLoadError(f"{path} has unknown fields: {', '.join(unknown)}")
    return cast(dict[str, object], raw)


def _records(raw: object, path: str) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        raise CalibrationLoadError(f"{path} must be an array of tables")
    if any(not isinstance(item, dict) for item in raw):
        raise CalibrationLoadError(f"{path} must contain only tables")
    return cast(list[dict[str, object]], raw)


def _string(raw: object, path: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise CalibrationLoadError(f"{path} must be a non-empty string")
    return raw


def _string_tuple(raw: object, path: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise CalibrationLoadError(f"{path} must be an array of strings")
    return tuple(_string(item, f"{path}[{index}]") for index, item in enumerate(raw))


def _integer(raw: object, path: str, *, minimum: int = 0) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < minimum:
        raise CalibrationLoadError(
            f"{path} must be an integer greater than or equal to {minimum}"
        )
    return raw


def _boolean(raw: object, path: str) -> bool:
    if not isinstance(raw, bool):
        raise CalibrationLoadError(f"{path} must be a boolean")
    return raw


def _uuid(raw: object, path: str) -> UUID:
    if not isinstance(raw, str):
        raise CalibrationLoadError(f"{path} must be a UUID string")
    try:
        return UUID(raw)
    except ValueError as exc:
        raise CalibrationLoadError(f"{path} must be a UUID string") from exc


def _paper_id(raw: object, path: str) -> str:
    paper_id = _string(raw, path)
    if not is_valid_paper_id(paper_id):
        raise CalibrationLoadError(f"{path} must be a canonical OpenAlex ID")
    return paper_id


def _label(raw: object, path: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw not in {0, 1, 2}:
        raise CalibrationLoadError(f"{path} must be one of 0, 1, or 2")
    return raw


def _unique(values: Iterable[object], description: str) -> None:
    seen: set[object] = set()
    for value in values:
        if value in seen:
            raise CalibrationLoadError(f"duplicate {description}: {value}")
        seen.add(value)
