"""Run calibration queries through injected search services and record outcomes."""

from __future__ import annotations

import time
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, cast
from uuid import UUID, uuid4

from research_platform.evaluation.calibration import CalibrationDataset
from research_platform.evaluation.matching import SourceEvidenceRegion
from research_platform.evaluation.run_records import (
    FailureCategory,
    HardwareDescriptor,
    LatencyKind,
    QueryRunRecord,
    RunRecordError,
    create_query_run_record,
    failed_search_attempt,
    successful_search_attempt,
)
from research_platform.evaluation.scoring import QueryFamilyScore, score_query_family
from research_platform.evaluation.source_alignment import SourceAlignmentDataset
from research_platform.search.contracts import (
    EvidenceHit,
    PaperHit,
    RetrievalMode,
    SearchOperation,
    SearchRequest,
    SearchResponse,
)


class SearchService(Protocol):
    """Async search boundary used by production adapters and deterministic fakes."""

    async def search(
        self, request: SearchRequest
    ) -> SearchResponse[PaperHit] | SearchResponse[EvidenceHit]: ...


class SearchServiceFailure(Exception):
    """A search adapter failure with a bounded category safe for run records."""

    def __init__(self, category: FailureCategory) -> None:
        if category not in {
            "timeout",
            "transport",
            "backend",
            "validation",
            "resource",
            "cancelled",
            "other",
        }:
            raise ValueError("unsupported search failure category")
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class EvaluationOptions:
    """Reproducible request settings shared across one calibration run."""

    retrieval_profile_id: str
    mode: RetrievalMode
    calibration_sha256: str
    source_alignment_sha256: str
    code_revision: str
    working_tree_dirty: bool = False
    working_tree_diff_sha256: str | None = None
    limit: int = 10
    latency_kind: LatencyKind = "warm"
    hardware: HardwareDescriptor | None = None
    experiment_id: str | None = None
    comparison_id: str | None = None
    random_seed: int | None = None


async def evaluate_calibration(
    search_service: SearchService,
    calibration: CalibrationDataset,
    alignments: SourceAlignmentDataset,
    *,
    options: EvaluationOptions,
    regions_by_evidence_id: Mapping[str, SourceEvidenceRegion],
    eligible_paper_ids_by_query: Mapping[str, Collection[str]] | None = None,
    run_ids_by_query: Mapping[str, UUID] | None = None,
    started_at: datetime | None = None,
) -> tuple[QueryRunRecord, ...]:
    """Search and score every calibration query without persisting passages.

    Search failures remain as failed attempts. A query receives no score unless both
    its paper and evidence requests returned valid responses.
    """
    run_started_at = started_at or datetime.now(timezone.utc)
    records: list[QueryRunRecord] = []
    for family in calibration.families:
        for query in family.queries:
            records.append(
                await _evaluate_query(
                    search_service,
                    calibration,
                    alignments,
                    family_id=family.id,
                    query_id=query.id,
                    options=options,
                    regions_by_evidence_id=regions_by_evidence_id,
                    eligible_paper_ids=(
                        eligible_paper_ids_by_query.get(query.id)
                        if eligible_paper_ids_by_query is not None
                        else None
                    ),
                    run_id=(
                        run_ids_by_query.get(query.id)
                        if run_ids_by_query is not None
                        else None
                    ),
                    started_at=run_started_at,
                )
            )
    return tuple(records)


async def _evaluate_query(
    search_service: SearchService,
    calibration: CalibrationDataset,
    alignments: SourceAlignmentDataset,
    *,
    family_id: str,
    query_id: str,
    options: EvaluationOptions,
    regions_by_evidence_id: Mapping[str, SourceEvidenceRegion],
    eligible_paper_ids: Collection[str] | None,
    run_id: UUID | None,
    started_at: datetime,
) -> QueryRunRecord:
    family = next((item for item in calibration.families if item.id == family_id), None)
    if family is None:
        raise RunRecordError(f"unknown calibration family: {family_id}")
    query = next((item for item in family.queries if item.id == query_id), None)
    if query is None:
        raise RunRecordError("query_id does not belong to family_id")

    attempts = []
    responses: dict[
        SearchOperation, SearchResponse[PaperHit] | SearchResponse[EvidenceHit]
    ] = {}
    for operation in (SearchOperation.PAPER_SEARCH, SearchOperation.EVIDENCE_SEARCH):
        request = SearchRequest(
            query=query.text,
            snapshot_id=calibration.snapshot_id,
            retrieval_profile_id=options.retrieval_profile_id,
            mode=options.mode,
            operation=operation,
            filters=family.filters,
            limit=options.limit,
        )
        attempt_id = uuid4()
        started = time.perf_counter()
        try:
            response = await search_service.search(request)
        except SearchServiceFailure as exc:
            attempts.append(
                failed_search_attempt(
                    request,
                    attempt_id=attempt_id,
                    latency_ms=_elapsed_ms(started),
                    latency_kind=options.latency_kind,
                    failure_category=exc.category,
                )
            )
            continue
        except Exception:
            attempts.append(
                failed_search_attempt(
                    request,
                    attempt_id=attempt_id,
                    latency_ms=_elapsed_ms(started),
                    latency_kind=options.latency_kind,
                    failure_category="other",
                )
            )
            continue
        try:
            attempts.append(
                successful_search_attempt(
                    request,
                    response,
                    attempt_id=attempt_id,
                    latency_ms=_elapsed_ms(started),
                    latency_kind=options.latency_kind,
                )
            )
        except (AttributeError, RunRecordError, TypeError, ValueError):
            attempts.append(
                failed_search_attempt(
                    request,
                    attempt_id=attempt_id,
                    latency_ms=_elapsed_ms(started),
                    latency_kind=options.latency_kind,
                    failure_category="validation",
                )
            )
            continue
        responses[operation] = response

    score: QueryFamilyScore | None = None
    paper_response = responses.get(SearchOperation.PAPER_SEARCH)
    evidence_response = responses.get(SearchOperation.EVIDENCE_SEARCH)
    if paper_response is not None and evidence_response is not None:
        paper_hits = cast(SearchResponse[PaperHit], paper_response).hits
        evidence_hits = cast(SearchResponse[EvidenceHit], evidence_response).hits
        score = score_query_family(
            calibration,
            family_id=family_id,
            query_id=query_id,
            paper_result_snapshot_id=paper_response.snapshot_id,
            evidence_result_snapshot_id=evidence_response.snapshot_id,
            paper_hits=paper_hits,
            evidence_hits=evidence_hits,
            regions_by_evidence_id=regions_by_evidence_id,
            alignments=alignments,
            eligible_paper_ids=eligible_paper_ids,
        )

    return create_query_run_record(
        calibration,
        alignments,
        family_id=family_id,
        query_id=query_id,
        calibration_sha256=options.calibration_sha256,
        source_alignment_sha256=options.source_alignment_sha256,
        code_revision=options.code_revision,
        working_tree_dirty=options.working_tree_dirty,
        working_tree_diff_sha256=options.working_tree_diff_sha256,
        hardware=options.hardware or HardwareDescriptor.capture_host(),
        attempts=tuple(attempts),
        score=score,
        experiment_id=options.experiment_id,
        comparison_id=options.comparison_id,
        random_seed=options.random_seed,
        run_id=run_id,
        started_at=started_at,
    )


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.perf_counter() - started) * 1000.0)
