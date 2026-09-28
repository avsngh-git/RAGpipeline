from uuid import UUID

from research_platform.evaluation.matching import (
    UnalignedEvidenceRegion,
    match_evidence_hits,
    region_from_evidence_unit,
    regions_from_search_hits,
)
from research_platform.evaluation.source_alignment import (
    CellCoordinate,
    SourceAlignmentDataset,
    TextAnchorAlignment,
    TextSpanRequirement,
)
from research_platform.ingestion.evidence import (
    EvidenceSourceSpan,
    EvidenceUnit,
    SourceLocation,
)
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
    TableCellEvidence,
    TableEvidenceContext,
    TableRowEvidence,
)


def test_unaligned_evidence_keeps_rank_without_matching_text_anchors() -> None:
    document_id = UUID("00000000-0000-0000-0000-000000000001")
    extraction_id = UUID("00000000-0000-0000-0000-000000000002")
    evidence_id = "sha256:" + "a" * 64
    unit = EvidenceUnit(
        id=evidence_id,
        document_id=document_id,
        extraction_id=extraction_id,
        section_ordinal=None,
        ordinal=0,
        kind="figure",
        content="figure caption",
        start_offset=None,
        end_offset=None,
        source_location=SourceLocation(),
    )
    region = region_from_evidence_unit(unit)
    assert isinstance(region, UnalignedEvidenceRegion)
    hit = EvidenceHit(
        chunk_id=evidence_id,
        source_evidence_ids=(evidence_id,),
        paper_id="W123",
        document_id=document_id,
        document_version="v1",
        document_version_kind="published",
        extraction_id=extraction_id,
        chunking_configuration_id=None,
        kind="figure",
        source_location=SourceLocation(),
        rank=7,
        component_scores=ComponentScores(),
        text="figure caption",
    )
    alignment = SourceAlignmentDataset(
        schema_version=1,
        alignment_id="fixture-alignment-v1",
        calibration_dataset_id="fixture-calibration-v1",
        snapshot_id=UUID("00000000-0000-0000-0000-000000000003"),
        policy_id="source-match-policy-v1",
        table_alignments=(),
        text_alignments=(
            TextAnchorAlignment(
                anchor_id="prose-anchor",
                document_id=document_id,
                extraction_id=extraction_id,
                spans=(TextSpanRequirement(0, 1, 10, 0.8),),
            ),
        ),
    )

    matches = match_evidence_hits((hit,), {evidence_id: region}, alignment)

    assert matches == ()


def test_regions_from_search_hits_preserves_text_source_spans() -> None:
    document_id = UUID("00000000-0000-0000-0000-000000000011")
    extraction_id = UUID("00000000-0000-0000-0000-000000000012")
    evidence_id = "sha256:" + "b" * 64
    hit = EvidenceHit(
        chunk_id="text-hit",
        source_evidence_ids=(evidence_id,),
        paper_id="W123",
        document_id=document_id,
        document_version="v1",
        document_version_kind="published",
        extraction_id=extraction_id,
        chunking_configuration_id=None,
        kind="text",
        source_location=SourceLocation(page_index_zero_based=1),
        rank=1,
        component_scores=ComponentScores(),
        text="The retrieved passage.",
        source_spans=(
            EvidenceSourceSpan(
                section_ordinal=2,
                start_offset=100,
                end_offset=122,
                chunk_start_offset=0,
                chunk_end_offset=22,
                heading_path=("Results",),
                source_location=SourceLocation(page_index_zero_based=1),
            ),
        ),
    )

    regions = regions_from_search_hits((hit,))

    region = regions[evidence_id]
    assert region.section_ordinal == 2
    assert region.start_offset == 100
    assert region.end_offset == 122


def test_regions_from_search_hits_uses_full_table_rows_and_context() -> None:
    document_id = UUID("00000000-0000-0000-0000-000000000021")
    extraction_id = UUID("00000000-0000-0000-0000-000000000022")
    evidence_id = "sha256:" + "c" * 64
    table_context = TableEvidenceContext(
        table_ordinal=3,
        header_row_count=1,
        caption="Table 3: retrieval results",
        units=None,
        footnotes=(),
        header_rows=(
            TableRowEvidence(
                row_index=0,
                cells=(
                    TableCellEvidence(0, 0, "Dataset", "cell"),
                    TableCellEvidence(0, 1, "Recall@20", "cell"),
                ),
            ),
        ),
        selected_rows=(
            TableRowEvidence(
                row_index=2,
                cells=(
                    TableCellEvidence(2, 0, "EntityQuestions", "cell"),
                    TableCellEvidence(2, 1, "71.2", "cell"),
                ),
            ),
        ),
        selected_cells=(),
        source_evidence_ids=(evidence_id,),
    )
    hit = EvidenceHit(
        chunk_id="table-hit",
        source_evidence_ids=(evidence_id,),
        paper_id="W123",
        document_id=document_id,
        document_version="v1",
        document_version_kind="published",
        extraction_id=extraction_id,
        chunking_configuration_id=None,
        kind="table_row_group",
        source_location=SourceLocation(page_index_zero_based=2),
        rank=1,
        component_scores=ComponentScores(),
        text="EntityQuestions 71.2",
        table_context=table_context,
    )

    region = regions_from_search_hits((hit,))[evidence_id]

    assert region.table_ordinal == 3
    assert {cell.cell for cell in region.cells} == {
        # Header cells are retained to validate method/dataset/metric context.
        CellCoordinate(0, 0),
        CellCoordinate(0, 1),
        CellCoordinate(2, 0),
        CellCoordinate(2, 1),
    }
    assert region.context_types == frozenset({"caption"})


def test_regions_from_search_hits_does_not_credit_partial_table_cell_as_full() -> None:
    document_id = UUID("00000000-0000-0000-0000-000000000031")
    extraction_id = UUID("00000000-0000-0000-0000-000000000032")
    evidence_id = "sha256:" + "d" * 64
    table_context = TableEvidenceContext(
        table_ordinal=0,
        header_row_count=1,
        caption="Table 1",
        units=None,
        footnotes=(),
        header_rows=(
            TableRowEvidence(
                row_index=0,
                cells=(TableCellEvidence(0, 0, "Model", "cell"),),
            ),
        ),
        selected_rows=(),
        selected_cells=(
            TableCellEvidence(
                row_index=1,
                column_index=0,
                value="0.50",
                value_scope="segment",
                token_start=0,
                token_end_exclusive=1,
            ),
        ),
        source_evidence_ids=(evidence_id,),
    )
    hit = EvidenceHit(
        chunk_id="partial-table-hit",
        source_evidence_ids=(evidence_id,),
        paper_id="W123",
        document_id=document_id,
        document_version="v1",
        document_version_kind="published",
        extraction_id=extraction_id,
        chunking_configuration_id=None,
        kind="table",
        source_location=SourceLocation(page_index_zero_based=0),
        rank=1,
        component_scores=ComponentScores(),
        text="Model 0.50",
        table_context=table_context,
    )

    region = regions_from_search_hits((hit,))[evidence_id]

    assert all(cell.cell.row != 1 for cell in region.cells)
