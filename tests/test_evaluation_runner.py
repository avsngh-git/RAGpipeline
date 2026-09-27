"""Behavioral checks for the public calibration evaluation runner."""

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from research_platform.evaluation.calibration import (
    CalibrationDataset,
    CalibrationQuery,
    CalibrationSourceAnchor,
    CalibrationSourceDocument,
    EvidenceJudgment,
    EvidenceRequirementGroup,
    PaperJudgment,
    QuestionFamily,
)
from research_platform.evaluation.matching import (
    TableCellCoverage,
    TableEvidenceRegion,
    TextEvidenceRegion,
    match_evidence_hits,
)
from research_platform.evaluation.run_records import (
    RunRecordError,
    sanitized_run_summary,
    write_run_record,
)
from research_platform.evaluation.runner import (
    EvaluationOptions,
    SearchServiceFailure,
    evaluate_calibration,
)
from research_platform.evaluation.scoring import (
    EvaluationScoringError,
    score_query_family,
)
from research_platform.evaluation.source_alignment import (
    CellCoordinate,
    SourceAlignmentDataset,
    TableAnchorAlignment,
    TableCellRequirement,
    TextAnchorAlignment,
    TextSpanRequirement,
)
from research_platform.ingestion.evidence import SourceLocation
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    PaperHit,
    RankedComponent,
    RetrievalMode,
    SearchFilters,
    SearchOperation,
    SearchRequest,
    SearchResponse,
)

SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000001")
EXTRACTION_ID = UUID("00000000-0000-0000-0000-000000000002")
PROFILE_ID = "sha256:" + "a" * 64
CONFIGURATION_ID = "sha256:" + "b" * 64
PAPER_ID = "W123"


class FakeSearchService:
    def __init__(self, responses: dict[SearchOperation, SearchResponse]) -> None:
        self.responses = responses
        self.requests: list[SearchRequest] = []

    async def search(
        self, request: SearchRequest
    ) -> SearchResponse[PaperHit] | SearchResponse[EvidenceHit]:
        self.requests.append(request)
        return self.responses[request.operation]


def calibrated_fixture() -> tuple[CalibrationDataset, SourceAlignmentDataset]:
    document = CalibrationSourceDocument(
        document_id=DOCUMENT_ID,
        paper_id=PAPER_ID,
        extraction_id=EXTRACTION_ID,
        pdf_sha256="c" * 64,
    )
    anchor = CalibrationSourceAnchor(
        id="result-anchor",
        document_id=DOCUMENT_ID,
        page_index_zero_based=2,
        region_type="prose",
        locator="page 3, paragraph 2",
        source_check="original_pdf_text_crosschecked",
    )
    family = QuestionFamily(
        id="method-result",
        split="development",
        categories=("specific_evidence",),
        reviewer_status="assistant_reviewed",
        reviewed_on=date(2026, 9, 26),
        filters=SearchFilters(),
        unsupported=False,
        requires_evidence=True,
        queries=(
            CalibrationQuery(
                id="method-result-v1",
                role="canonical",
                text="Which method reported the result?",
            ),
        ),
        paper_judgments=(
            PaperJudgment(paper_id=PAPER_ID, label=2, rationale="direct result"),
        ),
        evidence_judgments=(
            EvidenceJudgment(
                paper_id=PAPER_ID,
                source_anchor_id=anchor.id,
                label=2,
                rationale="reports the result",
            ),
        ),
        evidence_groups=(
            EvidenceRequirementGroup(
                id="result-group", required_pieces=((anchor.id,),)
            ),
        ),
    )
    calibration = CalibrationDataset(
        schema_version=1,
        dataset_id="synthetic-calibration-v1",
        dataset_kind="calibration",
        snapshot_id=SNAPSHOT_ID,
        split_policy_id="family-hash-split-v1",
        source_documents=(document,),
        source_anchors=(anchor,),
        families=(family,),
    )
    alignment = SourceAlignmentDataset(
        schema_version=1,
        alignment_id="synthetic-source-alignment-v1",
        calibration_dataset_id=calibration.dataset_id,
        snapshot_id=SNAPSHOT_ID,
        policy_id="source-match-policy-v1",
        table_alignments=(),
        text_alignments=(
            TextAnchorAlignment(
                anchor_id=anchor.id,
                document_id=DOCUMENT_ID,
                extraction_id=EXTRACTION_ID,
                spans=(
                    TextSpanRequirement(
                        section_ordinal=0,
                        start_offset=0,
                        end_offset=10,
                        minimum_coverage=0.8,
                    ),
                ),
            ),
        ),
    )
    return calibration, alignment


def test_evaluator_runs_fake_search_and_emits_a_text_free_scored_record() -> None:
    calibration, alignment = calibrated_fixture()
    evidence_hit = EvidenceHit(
        chunk_id="chunk-1",
        source_evidence_ids=("source-1",),
        paper_id=PAPER_ID,
        document_id=DOCUMENT_ID,
        document_version="published-1",
        document_version_kind="published",
        extraction_id=EXTRACTION_ID,
        chunking_configuration_id=None,
        kind="text",
        source_location=SourceLocation(page_index_zero_based=2),
        rank=1,
        component_scores=ComponentScores(dense=RankedComponent(rank=1, score=0.9)),
        text="private evidence excerpt",
    )
    paper_hit = PaperHit(
        paper_id=PAPER_ID,
        title="private paper title",
        publication_year=2024,
        rank=1,
        component_scores=ComponentScores(dense=RankedComponent(rank=1, score=0.9)),
        supporting_evidence=(evidence_hit,),
    )
    service = FakeSearchService(
        {
            SearchOperation.PAPER_SEARCH: SearchResponse(
                request_id="paper-request",
                snapshot_id=SNAPSHOT_ID,
                retrieval_profile_id=PROFILE_ID,
                effective_configuration_id=CONFIGURATION_ID,
                requested_mode=RetrievalMode.DENSE,
                effective_mode=RetrievalMode.DENSE,
                eligible_count=1,
                hits=(paper_hit,),
            ),
            SearchOperation.EVIDENCE_SEARCH: SearchResponse(
                request_id="evidence-request",
                snapshot_id=SNAPSHOT_ID,
                retrieval_profile_id=PROFILE_ID,
                effective_configuration_id=CONFIGURATION_ID,
                requested_mode=RetrievalMode.DENSE,
                effective_mode=RetrievalMode.DENSE,
                eligible_count=1,
                hits=(evidence_hit,),
            ),
        }
    )

    records = asyncio.run(
        evaluate_calibration(
            service,
            calibration,
            alignment,
            options=EvaluationOptions(
                retrieval_profile_id=PROFILE_ID,
                mode=RetrievalMode.DENSE,
                calibration_sha256="d" * 64,
                source_alignment_sha256="e" * 64,
                code_revision="abcdef0",
                hardware=None,
            ),
            regions_by_evidence_id={
                "source-1": TextEvidenceRegion(
                    evidence_id="source-1",
                    document_id=DOCUMENT_ID,
                    extraction_id=EXTRACTION_ID,
                    section_ordinal=0,
                    start_offset=0,
                    end_offset=10,
                ),
            },
            run_ids_by_query={
                "method-result-v1": UUID("00000000-0000-0000-0000-000000000010")
            },
            started_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        )
    )
    record = records[0]

    assert [request.operation for request in service.requests] == [
        SearchOperation.PAPER_SEARCH,
        SearchOperation.EVIDENCE_SEARCH,
    ]
    assert all(
        request.query == "Which method reported the result?"
        and request.snapshot_id == SNAPSHOT_ID
        and request.retrieval_profile_id == PROFILE_ID
        for request in service.requests
    )
    assert record.status == "complete"
    assert record.score is not None
    assert record.score.paper.ndcg_at_10.value == 1.0
    assert record.score.evidence.direct_mrr_at_10.value == 1.0
    serialized = json.dumps(record.to_dict())
    assert "private evidence excerpt" not in serialized
    assert "private paper title" not in serialized
    summary = json.dumps(sanitized_run_summary(record))
    assert "source-1" not in summary
    assert "raw_record_sha256" in summary


def make_evidence_hit(
    *,
    rank: int,
    evidence_id: str,
    paper_id: str = PAPER_ID,
    document_id: UUID = DOCUMENT_ID,
    extraction_id: UUID = EXTRACTION_ID,
) -> EvidenceHit:
    return EvidenceHit(
        chunk_id=f"chunk-{rank}-{evidence_id}",
        source_evidence_ids=(evidence_id,),
        paper_id=paper_id,
        document_id=document_id,
        document_version="published-1",
        document_version_kind="published",
        extraction_id=extraction_id,
        chunking_configuration_id=None,
        kind="text",
        source_location=SourceLocation(page_index_zero_based=2),
        rank=rank,
        component_scores=ComponentScores(),
        text="synthetic source passage",
    )


def score_fixture(
    calibration: CalibrationDataset,
    alignment: SourceAlignmentDataset,
    *,
    paper_hits: tuple[PaperHit, ...] = (),
    evidence_hits: tuple[EvidenceHit, ...] = (),
    regions: dict[str, TextEvidenceRegion | TableEvidenceRegion] | None = None,
):
    return score_query_family(
        calibration,
        family_id=calibration.families[0].id,
        query_id=calibration.families[0].queries[0].id,
        paper_result_snapshot_id=calibration.snapshot_id,
        evidence_result_snapshot_id=calibration.snapshot_id,
        paper_hits=paper_hits,
        evidence_hits=evidence_hits,
        regions_by_evidence_id=regions or {},
        alignments=alignment,
    )


def test_evidence_chunks_with_different_boundaries_accumulate_once() -> None:
    calibration, alignment = calibrated_fixture()
    hits = (
        make_evidence_hit(rank=1, evidence_id="left"),
        make_evidence_hit(rank=2, evidence_id="right"),
        make_evidence_hit(rank=3, evidence_id="left-duplicate"),
    )
    regions = {
        "left": TextEvidenceRegion("left", DOCUMENT_ID, EXTRACTION_ID, 0, 0, 6),
        "right": TextEvidenceRegion("right", DOCUMENT_ID, EXTRACTION_ID, 0, 5, 10),
        "left-duplicate": TextEvidenceRegion(
            "left-duplicate", DOCUMENT_ID, EXTRACTION_ID, 0, 0, 6
        ),
    }

    score = score_fixture(
        calibration,
        alignment,
        evidence_hits=hits,
        regions=regions,
    )

    assert score.evidence.direct_mrr_at_10.value == 0.5
    assert score.evidence.ndcg_at_10.value == pytest.approx(0.63093, abs=1e-5)
    assert score.evidence.judged_recall_at_20.value == 1.0
    assert score.evidence_group_coverage[0].complete_groups.value == 1.0
    matches = match_evidence_hits(hits, regions, alignment)
    assert len(matches) == 1
    assert matches[0].coverage_fraction == 1.0


def test_table_cell_partial_support_counts_for_direct_rank_but_not_full_group() -> None:
    calibration, _ = calibrated_fixture()
    anchor = replace(
        calibration.source_anchors[0],
        id="table-result",
        region_type="table",
        table_label="Table 1",
    )
    family = replace(
        calibration.families[0],
        evidence_judgments=(
            EvidenceJudgment(PAPER_ID, "table-result", 2, "direct table result"),
        ),
        evidence_groups=(
            EvidenceRequirementGroup("table-group", (("table-result",),)),
        ),
    )
    calibration = replace(calibration, source_anchors=(anchor,), families=(family,))
    alignment = SourceAlignmentDataset(
        schema_version=1,
        alignment_id="synthetic-table-alignment-v1",
        calibration_dataset_id=calibration.dataset_id,
        snapshot_id=SNAPSHOT_ID,
        policy_id="source-match-policy-v1",
        table_alignments=(
            TableAnchorAlignment(
                anchor_id="table-result",
                document_id=DOCUMENT_ID,
                extraction_id=EXTRACTION_ID,
                table_ordinal=0,
                cell_requirements=(
                    TableCellRequirement(CellCoordinate(1, 1), (CellCoordinate(0, 1),)),
                    TableCellRequirement(CellCoordinate(2, 1), (CellCoordinate(0, 1),)),
                ),
                required_context=("caption",),
            ),
        ),
        text_alignments=(),
    )
    evidence_hit = make_evidence_hit(rank=1, evidence_id="table-cell")
    regions = {
        "table-cell": TableEvidenceRegion(
            evidence_id="table-cell",
            document_id=DOCUMENT_ID,
            extraction_id=EXTRACTION_ID,
            table_ordinal=0,
            cells=(
                TableCellCoverage(CellCoordinate(1, 1), 0, 1, 1),
                TableCellCoverage(CellCoordinate(0, 1), 0, 1, 1),
            ),
            context_types=frozenset({"caption"}),
        ),
    }

    score = score_fixture(
        calibration,
        alignment,
        evidence_hits=(evidence_hit,),
        regions=regions,
    )
    match = match_evidence_hits((evidence_hit,), regions, alignment)[0]

    assert match.directly_supported is True
    assert match.fully_supported is False
    assert score.evidence.direct_mrr_at_10.value == 1.0
    assert score.evidence_group_coverage[0].required_pieces.value == 0.0
    assert score.evidence_group_coverage[0].complete_groups.value == 0.0


def test_repeated_papers_do_not_earn_extra_ndcg_gain_and_keep_rank_gaps() -> None:
    calibration, alignment = calibrated_fixture()
    family = replace(
        calibration.families[0],
        paper_judgments=(
            PaperJudgment(PAPER_ID, 2, "direct paper"),
            PaperJudgment("W456", 1, "useful context"),
        ),
    )
    calibration = replace(calibration, families=(family,))
    paper_hits = (
        PaperHit(PAPER_ID, "one", 2024, 1, ComponentScores()),
        PaperHit(PAPER_ID, "repeat", 2024, 2, ComponentScores()),
        PaperHit("W456", "context", 2023, 4, ComponentScores()),
        PaperHit("W999", "unjudged", 2022, 5, ComponentScores()),
    )

    score = score_fixture(calibration, alignment, paper_hits=paper_hits)

    assert score.paper.ndcg_at_10.value == pytest.approx(0.944848, abs=1e-6)
    assert score.paper.judgment_coverage.value == 0.75
    assert score.paper.judged_recall_at_20.value == 1.0


def test_no_positive_judgments_have_undefined_metrics_and_show_unjudged_hits() -> None:
    calibration, alignment = calibrated_fixture()
    family = replace(
        calibration.families[0],
        unsupported=True,
        requires_evidence=False,
        paper_judgments=(PaperJudgment(PAPER_ID, 0, "not relevant"),),
        evidence_judgments=(
            EvidenceJudgment(PAPER_ID, "result-anchor", 0, "not direct"),
        ),
        evidence_groups=(),
    )
    calibration = replace(calibration, families=(family,))
    other_document = UUID("00000000-0000-0000-0000-000000000003")
    other_extraction = UUID("00000000-0000-0000-0000-000000000004")
    paper_hits = (PaperHit("W999", "unjudged", None, 1, ComponentScores()),)
    evidence_hits = (
        make_evidence_hit(rank=1, evidence_id="source-1"),
        make_evidence_hit(
            rank=2,
            evidence_id="unjudged-source",
            paper_id="W999",
            document_id=other_document,
            extraction_id=other_extraction,
        ),
    )
    regions = {
        "source-1": TextEvidenceRegion(
            "source-1", DOCUMENT_ID, EXTRACTION_ID, 0, 0, 10
        ),
        "unjudged-source": TextEvidenceRegion(
            "unjudged-source", other_document, other_extraction, 0, 0, 10
        ),
    }

    score = score_fixture(
        calibration,
        alignment,
        paper_hits=paper_hits,
        evidence_hits=evidence_hits,
        regions=regions,
    )

    assert score.paper.ndcg_at_10.value is None
    assert score.paper.direct_mrr_at_10.value is None
    assert score.paper.judged_recall_at_20.value is None
    assert score.evidence.ndcg_at_10.value is None
    assert score.evidence.direct_mrr_at_10.value is None
    assert score.evidence.judged_recall_at_20.value is None
    assert score.unsupported_profile is not None
    assert score.unsupported_profile.paper_hits.unjudged == 1
    assert score.unsupported_profile.evidence_hits.unjudged == 1


def test_rank_ties_are_rejected() -> None:
    calibration, alignment = calibrated_fixture()
    paper_hits = (
        PaperHit(PAPER_ID, "first", 2024, 1, ComponentScores()),
        PaperHit("W456", "tied", 2023, 1, ComponentScores()),
    )

    with pytest.raises(EvaluationScoringError, match="duplicate result ranks"):
        score_fixture(calibration, alignment, paper_hits=paper_hits)


class FailingSearchService:
    async def search(self, request: SearchRequest) -> SearchResponse:
        if request.operation is SearchOperation.EVIDENCE_SEARCH:
            raise SearchServiceFailure("timeout")
        return SearchResponse(
            request_id="paper-request",
            snapshot_id=SNAPSHOT_ID,
            retrieval_profile_id=PROFILE_ID,
            effective_configuration_id=CONFIGURATION_ID,
            requested_mode=RetrievalMode.DENSE,
            effective_mode=RetrievalMode.DENSE,
            eligible_count=1,
            hits=(PaperHit(PAPER_ID, "paper", 2024, 1, ComponentScores()),),
        )


def test_failed_searches_are_retained_and_suppress_partial_scores() -> None:
    calibration, alignment = calibrated_fixture()
    records = asyncio.run(
        evaluate_calibration(
            FailingSearchService(),
            calibration,
            alignment,
            options=EvaluationOptions(
                retrieval_profile_id=PROFILE_ID,
                mode=RetrievalMode.DENSE,
                calibration_sha256="d" * 64,
                source_alignment_sha256="e" * 64,
                code_revision="abcdef0",
            ),
            regions_by_evidence_id={},
        )
    )

    assert len(records) == 1
    assert records[0].status == "partial"
    assert records[0].score is None
    assert [attempt.failure_category for attempt in records[0].attempts] == [
        None,
        "timeout",
    ]


def test_run_writer_serializes_privately_without_overwriting(tmp_path: Path) -> None:
    calibration, alignment = calibrated_fixture()
    record = asyncio.run(
        evaluate_calibration(
            FakeSearchService(
                {
                    SearchOperation.PAPER_SEARCH: SearchResponse(
                        "p",
                        SNAPSHOT_ID,
                        PROFILE_ID,
                        CONFIGURATION_ID,
                        RetrievalMode.DENSE,
                        RetrievalMode.DENSE,
                        (
                            PaperHit(
                                PAPER_ID, "private title", 2024, 1, ComponentScores()
                            ),
                        ),
                        1,
                    ),
                    SearchOperation.EVIDENCE_SEARCH: SearchResponse(
                        "e",
                        SNAPSHOT_ID,
                        PROFILE_ID,
                        CONFIGURATION_ID,
                        RetrievalMode.DENSE,
                        RetrievalMode.DENSE,
                        (),
                        0,
                    ),
                }
            ),
            calibration,
            alignment,
            options=EvaluationOptions(
                retrieval_profile_id=PROFILE_ID,
                mode=RetrievalMode.DENSE,
                calibration_sha256="d" * 64,
                source_alignment_sha256="e" * 64,
                code_revision="abcdef0",
            ),
            regions_by_evidence_id={},
        )
    )[0]
    root = Path(__file__).parents[1] / "local-reference" / "phase2-runs"
    destination = root / "tests" / f"{uuid4()}.json"
    try:
        written = write_run_record(destination, record)
        serialized = written.read_bytes()
        payload = json.loads(serialized)
        assert payload == record.to_dict()
        assert payload["schema_version"] == 2
        assert payload["attempts"][0]["eligible_count"] == 1
        assert payload["attempts"][0]["result_status"] == "ranked_candidates"
        assert payload["attempts"][0]["ranking_interpretation"] == "ranking_only"
        assert payload["attempts"][1]["eligible_count"] == 0
        assert payload["attempts"][1]["result_status"] == "no_eligible_records"
        assert (
            hashlib.sha256(serialized).hexdigest()
            == sanitized_run_summary(record)["raw_record_sha256"]
        )
        assert written.stat().st_mode & 0o777 == 0o600
        with pytest.raises(RunRecordError, match="already exists"):
            write_run_record(destination, record)
        assert written.read_bytes() == serialized
    finally:
        destination.unlink(missing_ok=True)
        destination.parent.rmdir()
