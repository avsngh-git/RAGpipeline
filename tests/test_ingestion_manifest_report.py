"""Tests for bounded, explainable discovery shortlist assessment."""

from uuid import uuid4

import pytest

from research_platform.ingestion.discovery_repository import (
    DiscoveryQuerySummary,
    DiscoveryRunSummary,
    ManifestCoverageReview,
    ManifestHeader,
    ManifestItem,
)
from research_platform.ingestion.manifest_report import build_manifest_review_report


def test_report_measures_review_yield_and_exposes_sampling_limits() -> None:
    manifest_id = uuid4()
    run_id = uuid4()
    header = ManifestHeader(
        id=manifest_id,
        run_id=run_id,
        version=1,
        status="draft",
        configuration_id="sha256:" + "1" * 64,
        code_revision="test-revision",
    )
    run = DiscoveryRunSummary(
        id=run_id,
        status="completed",
        request_count=4,
        result_count=3,
        api_cost_usd=0.02,
        configuration={"limits": {"max_pages_per_query": 2, "max_total_requests": 8}},
        queries=(
            DiscoveryQuerySummary(0, "hybrid", "search", 2, 3, True),
            DiscoveryQuerySummary(1, "reranking", "search", 1, 1, False),
        ),
    )
    items = (
        ManifestItem(
            "W1",
            "Included work",
            2024,
            "en",
            "article",
            "include",
            "Relevant",
            {"older_paper_exception": False, "has_abstract": True},
            {},
            ({"query_index": 0}, {"query_index": 1}),
            ("hybrid_dense",),
        ),
        ManifestItem(
            "W2",
            "Excluded work",
            2022,
            "en",
            "article",
            "exclude",
            "Out of scope",
            {"older_paper_exception": False, "has_abstract": False},
            {},
            ({"query_index": 0},),
            (),
        ),
        ManifestItem(
            "W3",
            None,
            None,
            None,
            None,
            "undecided",
            None,
            {"older_paper_exception": True},
            {},
            ({"query_index": 1},),
            (),
        ),
    )
    coverage = (
        ManifestCoverageReview("hybrid_dense", "covered", "Reviewed coverage."),
        ManifestCoverageReview("reranking_latency", "gap", "Needs more candidates."),
        ManifestCoverageReview("chunking_citation", "gap", "Not represented."),
    )

    report = build_manifest_review_report(header, run, items, coverage)

    assert report["review_yield"]["candidate_count"] == 3
    assert report["review_yield"]["reviewed"] == 2
    assert report["review_yield"]["reviewer_inclusion_share"] == pytest.approx(0.5)
    assert report["discovery"]["request_limit"] == 8
    assert report["discovery"]["truncated_queries"] == ["hybrid"]
    query_report = report["discovery"]["queries"]
    assert query_report[0]["shortlist_candidate_origins"] == 2
    assert query_report[1]["shortlist_candidate_origins"] == 2
    assert report["candidate_metadata_distribution"]["missing_fields"] == {
        "language": 1,
        "publication_year": 1,
        "title": 1,
    }
    assert "does not estimate recall" in report["limitations"][0]
