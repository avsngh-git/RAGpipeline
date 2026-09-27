from uuid import UUID

from research_platform.evaluation.matching import (
    UnalignedEvidenceRegion,
    match_evidence_hits,
    region_from_evidence_unit,
)
from research_platform.evaluation.source_alignment import (
    SourceAlignmentDataset,
    TextAnchorAlignment,
    TextSpanRequirement,
)
from research_platform.ingestion.evidence import (
    EvidenceUnit,
    SourceLocation,
)
from research_platform.search.contracts import (
    ComponentScores,
    EvidenceHit,
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
