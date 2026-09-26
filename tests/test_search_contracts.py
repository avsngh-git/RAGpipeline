"""Behavioral checks for typed paper/evidence search contracts."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from research_platform.api.schemas.search import (
    EvidenceSearchRequest,
    EvidenceSearchResponse,
    PaperMetadataResponse,
    PaperSearchResponse,
    SearchFiltersModel,
)
from research_platform.ingestion.evidence import SourceLocation
from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    ComponentScores,
    EvidenceHit,
    PaperHit,
    PaperMetadataHit,
    RankedComponent,
    RetrievalMode,
    SearchFilters,
    SearchLimits,
    SearchOperation,
    SearchResponse,
    matches_filters,
)

SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
PROFILE_ID = "sha256:" + "a" * 64


def valid_request_payload() -> dict[str, object]:
    return {
        "query": "  hybrid retrieval  ",
        "snapshot_id": str(SNAPSHOT_ID),
        "retrieval_profile_id": PROFILE_ID,
        "mode": "hybrid",
    }


def test_search_request_applies_bounded_defaults_and_normalizes_query() -> None:
    request = EvidenceSearchRequest.model_validate(valid_request_payload())

    assert request.query == "hybrid retrieval"
    assert request.limit == DEFAULT_SEARCH_LIMITS.default_result_limit
    assert request.filters.to_contract() == SearchFilters()
    contract = request.to_contract()
    assert contract.operation is SearchOperation.EVIDENCE_SEARCH
    assert contract.mode is RetrievalMode.HYBRID


def test_search_request_rejects_blank_oversized_and_unknown_values() -> None:
    payload = valid_request_payload()
    payload["query"] = "   "
    with pytest.raises(ValidationError, match="query must not be blank"):
        EvidenceSearchRequest.model_validate(payload)

    payload = valid_request_payload()
    payload["query"] = "q" * (DEFAULT_SEARCH_LIMITS.max_query_characters + 1)
    with pytest.raises(ValidationError):
        EvidenceSearchRequest.model_validate(payload)

    payload = valid_request_payload()
    payload["mode"] = "hybrid_plus"
    with pytest.raises(ValidationError):
        EvidenceSearchRequest.model_validate(payload)

    payload = valid_request_payload()
    payload["evidence_access_profile"] = "trusted_private_local"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EvidenceSearchRequest.model_validate(payload)


def test_search_request_rejects_invalid_ids_and_result_bounds() -> None:
    for field, value in (
        ("snapshot_id", "not-a-uuid"),
        ("retrieval_profile_id", "profile-1"),
        ("limit", 0),
        ("limit", DEFAULT_SEARCH_LIMITS.max_result_limit + 1),
    ):
        payload = valid_request_payload()
        payload[field] = value
        with pytest.raises(ValidationError):
            EvidenceSearchRequest.model_validate(payload)


def test_filters_reject_invalid_ranges_duplicate_values_and_ids() -> None:
    with pytest.raises(ValidationError, match="year_from must be less than"):
        SearchFiltersModel(year_from=2025, year_to=2024)
    with pytest.raises(ValidationError, match="paper_ids must not contain duplicates"):
        SearchFiltersModel(paper_ids=("W123", "W123"))
    with pytest.raises(ValidationError, match="canonical OpenAlex"):
        SearchFiltersModel(paper_ids=("https://openalex.org/W123",))
    with pytest.raises(
        ValidationError, match="evidence_kinds must not contain duplicates"
    ):
        SearchFiltersModel(evidence_kinds=("table", "table"))
    with pytest.raises(ValidationError):
        SearchFiltersModel.model_validate({"unknown_filter": True})


def test_filters_apply_and_across_fields_or_within_each_field() -> None:
    filters = SearchFilters(
        year_from=2020,
        year_to=2023,
        paper_ids=("W123", "W456"),
        evidence_kinds=("table", "table_row_group"),
        document_version_kinds=("published", "preprint"),
    )

    assert matches_filters(
        filters,
        operation=SearchOperation.EVIDENCE_SEARCH,
        paper_id="W123",
        publication_year=2022,
        evidence_kind="table_row_group",
        document_version_kind="published",
    )
    assert not matches_filters(
        filters,
        operation=SearchOperation.EVIDENCE_SEARCH,
        paper_id="W999",
        publication_year=2022,
        evidence_kind="table",
        document_version_kind="published",
    )
    assert not matches_filters(
        filters,
        operation=SearchOperation.EVIDENCE_SEARCH,
        paper_id="W123",
        publication_year=None,
        evidence_kind="table",
        document_version_kind="published",
    )
    assert not matches_filters(
        filters,
        operation=SearchOperation.EVIDENCE_SEARCH,
        paper_id="W123",
        publication_year=2022,
        evidence_kind=None,
        document_version_kind="published",
    )
    assert not matches_filters(
        filters,
        operation=SearchOperation.EVIDENCE_SEARCH,
        paper_id="W123",
        publication_year=2022,
        evidence_kind="table",
        document_version_kind="unknown",
    )


def test_evidence_filter_is_rejected_for_metadata_only_operation() -> None:
    filters = SearchFilters(evidence_kinds=("table",))

    with pytest.raises(ValueError, match="not supported for paper metadata"):
        filters.validate_for(SearchOperation.PAPER_METADATA)

    SearchFilters(year_from=2020).validate_for(SearchOperation.PAPER_METADATA)


def test_search_limits_are_validated_and_serializable() -> None:
    assert DEFAULT_SEARCH_LIMITS.to_dict()["max_candidate_limit"] == 200
    with pytest.raises(ValueError, match="default_result_limit"):
        SearchLimits(default_result_limit=51, max_result_limit=50)
    with pytest.raises(ValueError, match="request_timeout_seconds"):
        SearchLimits(request_timeout_seconds=float("inf"))


def test_response_schema_preserves_source_and_component_provenance() -> None:
    evidence = EvidenceHit(
        chunk_id="sha256:" + "b" * 64,
        source_evidence_ids=("sha256:" + "c" * 64,),
        paper_id="W123",
        document_id=UUID("91a7da33-066d-4c78-838a-413ba2f1b8d4"),
        document_version="published",
        document_version_kind="published",
        extraction_id=UUID("6715a62a-fb8c-41d3-812d-3130baf08f0f"),
        chunking_configuration_id="sha256:" + "d" * 64,
        kind="table_row_group",
        source_location=SourceLocation(page_index_zero_based=4),
        rank=1,
        component_scores=ComponentScores(
            lexical=RankedComponent(rank=2, score=13.5),
            dense=RankedComponent(rank=1, score=0.81),
            fusion=RankedComponent(rank=1, score=0.03),
            reranker=RankedComponent(rank=1, score=4.2),
        ),
        text="systematic review | 5",
    )
    paper = PaperHit(
        paper_id="W123",
        title="A study",
        publication_year=2022,
        rank=1,
        component_scores=evidence.component_scores,
        supporting_evidence=(evidence,),
    )
    response = SearchResponse[PaperHit](
        request_id="request-123",
        snapshot_id=SNAPSHOT_ID,
        retrieval_profile_id=PROFILE_ID,
        effective_configuration_id="sha256:" + "e" * 64,
        requested_mode=RetrievalMode.RERANKED,
        effective_mode=RetrievalMode.HYBRID,
        hits=(paper,),
        warnings=("reranker unavailable; fused order returned",),
        truncated=True,
        omitted_count=2,
    )

    serialized_papers = PaperSearchResponse.from_contract(response)
    evidence_response = SearchResponse[EvidenceHit](
        request_id="request-124",
        snapshot_id=SNAPSHOT_ID,
        retrieval_profile_id=PROFILE_ID,
        effective_configuration_id="sha256:" + "e" * 64,
        requested_mode=RetrievalMode.RERANKED,
        effective_mode=RetrievalMode.RERANKED,
        hits=(evidence,),
    )
    serialized_evidence = EvidenceSearchResponse.from_contract(evidence_response)

    assert serialized_papers.request_id == "request-123"
    assert serialized_papers.effective_mode is RetrievalMode.HYBRID
    assert serialized_papers.truncated is True
    assert (
        serialized_papers.hits[0].supporting_evidence[0].document_version == "published"
    )
    assert serialized_evidence.hits[0].source_location.page_index_zero_based == 4
    assert serialized_evidence.hits[0].component_scores.reranker.score == 4.2


def test_metadata_response_has_no_evidence_or_passage_field() -> None:
    metadata_response = SearchResponse[PaperMetadataHit](
        request_id="request-meta",
        snapshot_id=SNAPSHOT_ID,
        retrieval_profile_id=PROFILE_ID,
        effective_configuration_id="sha256:" + "e" * 64,
        requested_mode=RetrievalMode.LEXICAL,
        effective_mode=RetrievalMode.LEXICAL,
        hits=(
            PaperMetadataHit(
                paper_id="W123",
                title="A study",
                publication_year=2022,
                rank=1,
                component_scores=ComponentScores(
                    lexical=RankedComponent(rank=1, score=4.0)
                ),
            ),
        ),
    )

    serialized = PaperMetadataResponse.from_contract(metadata_response)
    assert serialized.hits[0].paper_id == "W123"
    assert not hasattr(serialized.hits[0], "supporting_evidence")
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PaperMetadataResponse.model_validate(
            {
                **metadata_response.__dict__,
                "hits": [{"paper_id": "W123", "text": "private passage"}],
            }
        )


def test_response_schema_enforces_result_and_per_paper_evidence_bounds() -> None:
    hit = EvidenceHit(
        chunk_id="sha256:" + "b" * 64,
        source_evidence_ids=("sha256:" + "c" * 64,),
        paper_id="W123",
        document_id=UUID("91a7da33-066d-4c78-838a-413ba2f1b8d4"),
        document_version="published",
        document_version_kind="published",
        extraction_id=UUID("6715a62a-fb8c-41d3-812d-3130baf08f0f"),
        chunking_configuration_id=None,
        kind="text",
        source_location=SourceLocation(),
        rank=1,
        component_scores=ComponentScores(),
        text="evidence",
    )
    paper = PaperHit(
        paper_id="W123",
        title="A study",
        publication_year=2022,
        rank=1,
        component_scores=ComponentScores(),
        supporting_evidence=(
            hit,
            hit,
            hit,
            hit,
            hit,
            hit,
        ),
    )
    response = SearchResponse[PaperHit](
        request_id="request-bounds",
        snapshot_id=SNAPSHOT_ID,
        retrieval_profile_id=PROFILE_ID,
        effective_configuration_id="sha256:" + "e" * 64,
        requested_mode=RetrievalMode.HYBRID,
        effective_mode=RetrievalMode.HYBRID,
        hits=(paper,),
    )

    with pytest.raises(ValidationError):
        PaperSearchResponse.from_contract(response)
