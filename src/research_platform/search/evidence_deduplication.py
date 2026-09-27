"""Conservatively remove repeated source coverage from ranked evidence hits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias
from uuid import UUID

from research_platform.ingestion.evidence import (
    EvidenceUnit,
    source_spans_for_evidence_unit,
)
from research_platform.search.contracts import EvidenceHit

EvidenceOmissionReason = Literal["duplicate_chunk_id", "source_coverage_subsumed"]


@dataclass(frozen=True)
class EvidenceHitOmission:
    """One ranked hit omitted with the earlier hit IDs that preserve its source."""

    chunk_id: str
    original_rank: int
    reason: EvidenceOmissionReason
    source_evidence_ids: tuple[str, ...]
    covered_by_chunk_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, str) or not self.chunk_id.strip():
            raise ValueError("chunk_id must be non-empty")
        if (
            isinstance(self.original_rank, bool)
            or not isinstance(self.original_rank, int)
            or self.original_rank < 1
        ):
            raise ValueError("original_rank must be a positive integer")
        if self.reason not in {"duplicate_chunk_id", "source_coverage_subsumed"}:
            raise ValueError("unsupported evidence omission reason")
        if not isinstance(self.source_evidence_ids, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.source_evidence_ids
        ):
            raise ValueError("source_evidence_ids must contain source IDs")
        if not isinstance(self.covered_by_chunk_ids, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.covered_by_chunk_ids
        ):
            raise ValueError("covered_by_chunk_ids must contain retained chunk IDs")
        if not self.covered_by_chunk_ids:
            raise ValueError("an omission must identify retained covering hits")


@dataclass(frozen=True)
class EvidenceDeduplicationResult:
    """Retained ranked hits and auditable duplicate/source-coverage omissions."""

    hits: tuple[EvidenceHit, ...]
    omissions: tuple[EvidenceHitOmission, ...]
    candidate_count: int
    unresolved_source_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.hits, tuple) or any(
            not isinstance(hit, EvidenceHit) for hit in self.hits
        ):
            raise ValueError("hits must contain EvidenceHit values")
        if not isinstance(self.omissions, tuple) or any(
            not isinstance(item, EvidenceHitOmission) for item in self.omissions
        ):
            raise ValueError("omissions must contain EvidenceHitOmission values")
        if (
            isinstance(self.candidate_count, bool)
            or not isinstance(self.candidate_count, int)
            or self.candidate_count < 0
        ):
            raise ValueError("candidate_count must be non-negative")
        if self.candidate_count != len(self.hits) + len(self.omissions):
            raise ValueError(
                "candidate_count must account for retained and omitted hits"
            )
        if not isinstance(self.unresolved_source_evidence_ids, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.unresolved_source_evidence_ids
        ):
            raise ValueError("unresolved source IDs must be non-empty strings")


class EvidenceDeduplicationError(ValueError):
    """Candidate or source-unit lineage is inconsistent and cannot be deduplicated."""


@dataclass(frozen=True)
class _TextSpan:
    extraction_id: UUID
    section_ordinal: int
    start: int
    end: int


@dataclass(frozen=True)
class _TableRows:
    extraction_id: UUID
    table_ordinal: int
    start_row: int
    end_row: int


@dataclass(frozen=True)
class _TableCellSpan:
    extraction_id: UUID
    table_ordinal: int
    row: int
    column: int
    start: int
    end: int


_SourceRegion: TypeAlias = _TextSpan | _TableRows | _TableCellSpan


class _CoverageIndex:
    """Union source intervals while keeping text, rows and cell segments distinct."""

    def __init__(self) -> None:
        self.text: dict[tuple[UUID, int], list[tuple[int, int]]] = {}
        self.rows: dict[tuple[UUID, int], list[tuple[int, int]]] = {}
        self.cells: dict[tuple[UUID, int, int, int], list[tuple[int, int]]] = {}

    def add(self, region: _SourceRegion) -> None:
        if isinstance(region, _TextSpan):
            self.text.setdefault(
                (region.extraction_id, region.section_ordinal), []
            ).append((region.start, region.end))
        elif isinstance(region, _TableRows):
            self.rows.setdefault(
                (region.extraction_id, region.table_ordinal), []
            ).append((region.start_row, region.end_row))
        else:
            self.cells.setdefault(
                (region.extraction_id, region.table_ordinal, region.row, region.column),
                [],
            ).append((region.start, region.end))

    def covers(self, region: _SourceRegion) -> bool:
        if isinstance(region, _TextSpan):
            intervals = self.text.get(
                (region.extraction_id, region.section_ordinal), ()
            )
            return _interval_is_covered(region.start, region.end, intervals)
        table_key = (region.extraction_id, region.table_ordinal)
        if isinstance(region, _TableRows):
            return _interval_is_covered(
                region.start_row,
                region.end_row,
                self.rows.get(table_key, ()),
            )
        cell_key = (
            region.extraction_id,
            region.table_ordinal,
            region.row,
            region.column,
        )
        return _interval_is_covered(
            region.start,
            region.end,
            self.cells.get(cell_key, ()),
        ) or any(
            start_row <= region.row < end_row
            for start_row, end_row in self.rows.get(table_key, ())
        )

    def overlaps(self, region: _SourceRegion) -> bool:
        if isinstance(region, _TextSpan):
            intervals = self.text.get(
                (region.extraction_id, region.section_ordinal), ()
            )
            return any(
                start < region.end and end > region.start for start, end in intervals
            )
        table_key = (region.extraction_id, region.table_ordinal)
        if isinstance(region, _TableRows):
            if any(
                start < region.end_row and end > region.start_row
                for start, end in self.rows.get(table_key, ())
            ):
                return True
            return any(
                key[0] == region.extraction_id
                and key[1] == region.table_ordinal
                and region.start_row <= key[2] < region.end_row
                for key in self.cells
            )
        cell_key = (
            region.extraction_id,
            region.table_ordinal,
            region.row,
            region.column,
        )
        if any(
            start < region.end and end > region.start
            for start, end in self.cells.get(cell_key, ())
        ):
            return True
        return any(
            start_row <= region.row < end_row
            for start_row, end_row in self.rows.get(table_key, ())
        )


def deduplicate_evidence_hits(
    candidates: Sequence[EvidenceHit],
    *,
    source_units_by_id: Mapping[str, EvidenceUnit],
) -> EvidenceDeduplicationResult:
    """Drop exact chunk repeats and hits fully covered by higher-ranked sources.

    Candidates are considered in ``(rank, chunk_id)`` order. Source overlap is only
    removed when the candidate's complete resolved coverage is already present in
    earlier retained hits. Partial overlaps remain intact so their unique source text,
    rows or cell segments are not lost. Repeated table headers are context and do not
    count as row overlap; disjoint row groups remain distinct.
    """
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise ValueError("candidates must be a sequence of EvidenceHit values")
    if not isinstance(source_units_by_id, Mapping):
        raise ValueError("source_units_by_id must map IDs to EvidenceUnit values")
    hits = tuple(candidates)
    if any(not isinstance(hit, EvidenceHit) for hit in hits):
        raise TypeError("candidates must contain EvidenceHit values")
    ranks = tuple(hit.rank for hit in hits)
    if len(set(ranks)) != len(ranks):
        raise EvidenceDeduplicationError("candidate ranks must be unique")

    ordered = tuple(sorted(hits, key=lambda hit: (hit.rank, hit.chunk_id)))
    retained: list[EvidenceHit] = []
    omissions: list[EvidenceHitOmission] = []
    unresolved_ids: list[str] = []
    seen_by_chunk_id: dict[str, EvidenceHit] = {}
    covering_ids_by_chunk_id: dict[str, tuple[str, ...]] = {}
    retained_indexes: dict[str, _CoverageIndex] = {}
    coverage = _CoverageIndex()

    for hit in ordered:
        prior_same_id = seen_by_chunk_id.get(hit.chunk_id)
        if prior_same_id is not None:
            if not _same_source_payload(prior_same_id, hit):
                raise EvidenceDeduplicationError(
                    "one chunk ID refers to conflicting source evidence"
                )
            omissions.append(
                EvidenceHitOmission(
                    chunk_id=hit.chunk_id,
                    original_rank=hit.rank,
                    reason="duplicate_chunk_id",
                    source_evidence_ids=hit.source_evidence_ids,
                    covered_by_chunk_ids=covering_ids_by_chunk_id[hit.chunk_id],
                )
            )
            continue
        seen_by_chunk_id[hit.chunk_id] = hit

        regions, missing_ids = _resolve_source_regions(hit, source_units_by_id)
        unresolved_ids.extend(missing_ids)
        if (
            regions
            and not missing_ids
            and all(coverage.covers(item) for item in regions)
        ):
            covered_by = tuple(
                sorted(
                    chunk_id
                    for chunk_id, prior_index in retained_indexes.items()
                    if any(prior_index.overlaps(region) for region in regions)
                )
            )
            if not covered_by:
                raise EvidenceDeduplicationError(
                    "source coverage was marked covered without retained source hits"
                )
            omissions.append(
                EvidenceHitOmission(
                    chunk_id=hit.chunk_id,
                    original_rank=hit.rank,
                    reason="source_coverage_subsumed",
                    source_evidence_ids=hit.source_evidence_ids,
                    covered_by_chunk_ids=covered_by,
                )
            )
            covering_ids_by_chunk_id[hit.chunk_id] = covered_by
            continue

        retained.append(hit)
        retained_indexes[hit.chunk_id] = _CoverageIndex()
        for region in regions:
            coverage.add(region)
            retained_indexes[hit.chunk_id].add(region)
        covering_ids_by_chunk_id[hit.chunk_id] = (hit.chunk_id,)

    return EvidenceDeduplicationResult(
        hits=tuple(retained),
        omissions=tuple(omissions),
        candidate_count=len(hits),
        unresolved_source_evidence_ids=tuple(dict.fromkeys(unresolved_ids)),
    )


def _resolve_source_regions(
    hit: EvidenceHit,
    source_units_by_id: Mapping[str, EvidenceUnit],
) -> tuple[tuple[_SourceRegion, ...], tuple[str, ...]]:
    regions: list[_SourceRegion] = []
    missing: list[str] = []
    for evidence_id in dict.fromkeys(hit.source_evidence_ids):
        unit = source_units_by_id.get(evidence_id)
        if unit is None:
            missing.append(evidence_id)
            continue
        if not isinstance(unit, EvidenceUnit):
            raise TypeError("source_units_by_id must contain EvidenceUnit values")
        if unit.id != evidence_id:
            raise EvidenceDeduplicationError(
                "resolved source unit has a different evidence ID"
            )
        if unit.extraction_id != hit.extraction_id:
            raise EvidenceDeduplicationError(
                "source unit extraction does not match the evidence hit"
            )
        if unit.document_id != hit.document_id:
            raise EvidenceDeduplicationError(
                "source unit document does not match the evidence hit"
            )
        source_regions = _regions_from_source_unit(unit)
        if not source_regions:
            missing.append(evidence_id)
        else:
            regions.extend(source_regions)
    return tuple(regions), tuple(missing)


def _regions_from_source_unit(unit: EvidenceUnit) -> tuple[_SourceRegion, ...]:
    if unit.kind == "text":
        try:
            spans = source_spans_for_evidence_unit(unit)
        except ValueError as error:
            raise EvidenceDeduplicationError(str(error)) from error
        return tuple(
            _TextSpan(
                unit.extraction_id,
                span.section_ordinal,
                span.start_offset,
                span.end_offset,
            )
            for span in spans
        )
    if unit.kind not in {"table", "table_row_group"}:
        return ()

    table_ordinal = _metadata_int(unit.metadata, "table_ordinal")
    cell_row = unit.metadata.get("cell_row")
    cell_column = unit.metadata.get("cell_column")
    if cell_row is not None or cell_column is not None:
        row = _metadata_value(cell_row, "cell_row")
        column = _metadata_value(cell_column, "cell_column")
        start = _metadata_int(unit.metadata, "cell_token_start")
        end = _metadata_int(unit.metadata, "cell_token_end_exclusive")
        if row < 0 or column < 0 or start < 0 or end <= start:
            return ()
        return (
            _TableCellSpan(unit.extraction_id, table_ordinal, row, column, start, end),
        )

    start_row = _metadata_int(unit.metadata, "row_start_inclusive")
    end_row = _metadata_int(unit.metadata, "row_end_exclusive")
    repeated_headers = _metadata_int(unit.metadata, "header_rows_repeated")
    if start_row < repeated_headers or end_row <= start_row:
        return ()
    return (_TableRows(unit.extraction_id, table_ordinal, start_row, end_row),)


def _metadata_int(metadata: Mapping[str, object], name: str) -> int:
    return _metadata_value(metadata.get(name), name)


def _metadata_value(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceDeduplicationError(
            f"source unit is missing a valid {name} coordinate"
        )
    return value


def _interval_is_covered(
    start: int, end: int, intervals: Sequence[tuple[int, int]]
) -> bool:
    position = start
    for interval_start, interval_end in sorted(intervals):
        if interval_end <= position:
            continue
        if interval_start > position:
            return False
        position = max(position, interval_end)
        if position >= end:
            return True
    return False


def _same_source_payload(first: EvidenceHit, second: EvidenceHit) -> bool:
    return all(
        getattr(first, field) == getattr(second, field)
        for field in (
            "source_evidence_ids",
            "paper_id",
            "document_id",
            "document_version",
            "document_version_kind",
            "extraction_id",
            "chunking_configuration_id",
            "kind",
            "source_location",
            "text",
            "table_context",
        )
    )
