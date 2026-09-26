"""Validation for the delegated 100-paper membership record."""

import hashlib
import json
from pathlib import Path

import pytest

from research_platform.ingestion.membership import MembershipDecision


def _write_membership(tmp_path: Path) -> Path:
    proposal_path = tmp_path / "proposal.json"
    ids = [f"W{index}" for index in range(100, 200)]
    proposal = {
        "items": [
            {
                "openalex_id": openalex_id,
                "title": f"Title {openalex_id}",
                "publication_year": 2024,
                "selection_rationale": "in-scope research record",
                "source_name": "OpenAlex cached PDF",
                "source_url": f"https://content.openalex.org/works/{openalex_id}.pdf",
                "version": "publishedVersion",
                "terms_url": "https://example.org/terms",
                "license_id": "cc-by",
                "pool": "finalized_expansion_screen",
            }
            for openalex_id in ids
        ]
    }
    proposal_bytes = json.dumps(proposal, sort_keys=True).encode()
    proposal_path.write_bytes(proposal_bytes)
    proposal_digest = "sha256:" + hashlib.sha256(proposal_bytes).hexdigest()
    decision = {
        "schema_version": 1,
        "record_type": "phase1_100_paper_membership_decision",
        "status": "membership_approved_pending_acquisition_checks",
        "total_unique_items": 100,
        "source_proposal": {
            "path": str(proposal_path),
            "sha256_after_decision": proposal_digest,
        },
        "decisions": [
            {
                "openalex_id": openalex_id,
                "title": f"Title {openalex_id}",
                "publication_year": 2024,
                "decision": "include",
                "reason": "in-scope research record",
            }
            for openalex_id in ids
        ],
    }
    decision_path = tmp_path / "membership.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    return decision_path


def test_membership_decision_binds_exactly_100_unique_titles_to_proposal(
    tmp_path: Path,
) -> None:
    decision_path = _write_membership(tmp_path)

    decision = MembershipDecision.load(decision_path)

    assert len(decision.selected_openalex_ids) == 100
    assert len(decision.selected_sources) == 100
    assert (
        decision.identity
        == "sha256:" + hashlib.sha256(decision_path.read_bytes()).hexdigest()
    )


def test_membership_decision_rejects_changed_source_proposal(tmp_path: Path) -> None:
    decision_path = _write_membership(tmp_path)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text('{"items": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="changed after review"):
        MembershipDecision.load(decision_path)


def test_source_route_review_applies_only_canonical_acl_url_fixes(
    tmp_path: Path,
) -> None:
    decision_path = _write_membership(tmp_path)
    decision_data = json.loads(decision_path.read_text(encoding="utf-8"))
    proposal_path = Path(decision_data["source_proposal"]["path"])
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    malformed = "https://aclanthology.org/https://aclanthology.org/2024.acl-long.1/"
    canonical = "https://aclanthology.org/2024.acl-long.1/"
    proposal["items"][0]["terms_url"] = malformed
    proposal_bytes = json.dumps(proposal, sort_keys=True).encode("utf-8")
    proposal_path.write_bytes(proposal_bytes)
    decision_data["source_proposal"]["sha256_after_decision"] = (
        "sha256:" + hashlib.sha256(proposal_bytes).hexdigest()
    )
    decision_path.write_text(json.dumps(decision_data), encoding="utf-8")
    membership = MembershipDecision.load(decision_path)

    review_path = tmp_path / "source-route-review.json"
    review_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "record_type": "phase1_100_source_route_review",
                "membership_decision_id": membership.identity,
                "reviewer": "assistant",
                "canonical_link_corrections": [
                    {
                        "openalex_id": "W100",
                        "original_terms_url": malformed,
                        "canonical_terms_url": canonical,
                        "evidence_url": canonical,
                    }
                ],
                "arxiv_license_checks": [],
            }
        ),
        encoding="utf-8",
    )

    reviewed = membership.with_source_route_review(review_path)

    assert reviewed.identity == membership.identity
    assert reviewed.selected_sources["W100"].terms_url == canonical
    assert reviewed.source_route_review_identity == (
        "sha256:" + hashlib.sha256(review_path.read_bytes()).hexdigest()
    )
