"""Tests for stable identifiers and selected document-version preference."""

from datetime import datetime, timezone

import pytest

from research_platform.ingestion.identity import (
    DocumentVersion,
    ExternalIdentifier,
    choose_preferred_document_version,
)


def test_openalex_ids_normalize_from_url() -> None:
    identifier = ExternalIdentifier("openalex", "https://openalex.org/W123")

    assert identifier.normalized_value == "W123"


@pytest.mark.parametrize(
    "value",
    ["https://doi.org/10.1234/Example", "doi:10.1234/EXAMPLE"],
)
def test_dois_normalize_to_lowercase_identifier(value: str) -> None:
    identifier = ExternalIdentifier("doi", value)

    assert identifier.normalized_value == "10.1234/example"


def test_arxiv_versions_share_a_logical_paper_identifier() -> None:
    first = ExternalIdentifier("arxiv", "https://arxiv.org/abs/2401.12345v1")
    second = ExternalIdentifier("arxiv", "2401.12345v4")

    assert first.normalized_value == second.normalized_value == "2401.12345"


def test_pmid_url_normalizes_to_digits() -> None:
    identifier = ExternalIdentifier("pmid", "https://pubmed.ncbi.nlm.nih.gov/123456/")

    assert identifier.normalized_value == "123456"


@pytest.mark.parametrize(
    ("namespace", "value"),
    [
        ("openalex", "not-a-work-id"),
        ("doi", "not-a-doi"),
        ("arxiv", "not-an-arxiv-id"),
        ("pmid", "pmid-123"),
    ],
)
def test_invalid_external_identifiers_fail_clearly(namespace: str, value: str) -> None:
    with pytest.raises(ValueError):
        ExternalIdentifier(namespace, value)  # type: ignore[arg-type]


def test_preference_uses_published_version_when_indexing_is_permitted() -> None:
    preprint = DocumentVersion(
        "preprint", "preprint", True, source_type="arxiv", version_label="v2"
    )
    published = DocumentVersion(
        "published",
        "published",
        True,
        datetime(2023, 1, 1, tzinfo=timezone.utc),
        source_type="publisher",
        version_label="version-of-record",
    )

    assert choose_preferred_document_version((preprint, published)) == published


def test_preference_falls_back_to_permitted_preprint() -> None:
    published_not_permitted = DocumentVersion(
        "published", "published", False, source_type="publisher"
    )
    preprint = DocumentVersion("preprint", "preprint", True, source_type="repository")

    assert (
        choose_preferred_document_version((published_not_permitted, preprint))
        == preprint
    )


def test_preference_skips_unclassified_or_unpermitted_versions() -> None:
    versions = (
        DocumentVersion("unknown", "unknown", True),
        DocumentVersion("other", "other", True),
        DocumentVersion("preprint", "preprint", False),
    )

    assert choose_preferred_document_version(versions) is None


def test_latest_of_multiple_published_versions_is_selected_deterministically() -> None:
    older = DocumentVersion(
        "older", "published", True, datetime(2022, 1, 1), source_type="publisher"
    )
    newer = DocumentVersion(
        "newer", "published", True, datetime(2024, 1, 1), source_type="publisher"
    )

    assert choose_preferred_document_version((older, newer)) == newer


def test_identifier_urls_normalize_case_and_file_suffixes() -> None:
    doi = ExternalIdentifier("doi", "HTTPS://DOI.ORG/10.1234/Example")
    arxiv = ExternalIdentifier("arxiv", "http://arxiv.org/pdf/2401.12345v3.pdf")
    pmid = ExternalIdentifier("pmid", "http://pubmed.ncbi.nlm.nih.gov/123456/")

    assert doi.normalized_value == "10.1234/example"
    assert arxiv.normalized_value == "2401.12345"
    assert pmid.normalized_value == "123456"


def test_naive_and_aware_publication_dates_are_compared_deterministically() -> None:
    same_instant_naive = DocumentVersion(
        "naive", "published", True, datetime(2024, 1, 1), source_type="same"
    )
    same_instant_utc = DocumentVersion(
        "aware",
        "published",
        True,
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        source_type="same",
    )
    unknown_date = DocumentVersion("unknown-date", "published", True)

    assert (
        choose_preferred_document_version(
            (unknown_date, same_instant_utc, same_instant_naive)
        )
        == same_instant_utc
    )
