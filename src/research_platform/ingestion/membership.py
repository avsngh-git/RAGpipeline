"""Validated membership decisions for the delegated Phase 1 corpus pilot."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import cast
from urllib.parse import urlsplit

_OPENALEX_ID = re.compile(r"^W[0-9]+$")
_SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class SelectedSourceRoute:
    """The selected PDF route and document version from the hashed proposal."""

    source_name: str
    source_url: str
    version: str
    terms_url: str | None
    license_id: str
    pool: str


@dataclass(frozen=True)
class MembershipDecision:
    """An immutable, file-bound 100-title membership decision."""

    identity: str
    selected_openalex_ids: frozenset[str]
    selected_titles: Mapping[str, str]
    publication_years: Mapping[str, int]
    selection_reasons: Mapping[str, str]
    selected_sources: Mapping[str, SelectedSourceRoute]
    source_route_review_identity: str | None = None

    @classmethod
    def load(cls, decision_path: Path) -> MembershipDecision:
        """Load and verify the approved decision and the proposal it records."""
        try:
            decision_bytes = decision_path.read_bytes()
            raw = json.loads(decision_bytes)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("membership decision file cannot be read") from error
        if not isinstance(raw, Mapping):
            raise ValueError("membership decision must be a JSON object")
        if raw.get("schema_version") != 1 or isinstance(
            raw.get("schema_version"), bool
        ):
            raise ValueError("unsupported membership decision schema")
        if raw.get("record_type") != "phase1_100_paper_membership_decision":
            raise ValueError("file is not a Phase 1 100-paper membership decision")
        if raw.get("status") != "membership_approved_pending_acquisition_checks":
            raise ValueError("100-paper membership decision is not approved")
        if raw.get("total_unique_items") != 100:
            raise ValueError("membership decision must select exactly 100 papers")

        source_value = raw.get("source_proposal")
        source = _mapping(source_value, "source_proposal")
        proposal_path_value = source.get("path")
        expected_proposal_digest = source.get("sha256_after_decision")
        if not isinstance(proposal_path_value, str) or not proposal_path_value.strip():
            raise ValueError("membership decision has no source proposal path")
        if not isinstance(expected_proposal_digest, str) or not _SHA256_ID.fullmatch(
            expected_proposal_digest
        ):
            raise ValueError("membership decision has an invalid proposal fingerprint")
        proposal_path = Path(proposal_path_value)
        if not proposal_path.is_absolute():
            proposal_path = Path.cwd() / proposal_path
        try:
            proposal_bytes = proposal_path.read_bytes()
            proposal = json.loads(proposal_bytes)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("membership source proposal cannot be read") from error
        actual_proposal_digest = "sha256:" + hashlib.sha256(proposal_bytes).hexdigest()
        if actual_proposal_digest != expected_proposal_digest:
            raise ValueError("membership source proposal changed after review")
        proposal_mapping = _mapping(proposal, "source proposal")
        proposal_items = proposal_mapping.get("items")
        if not isinstance(proposal_items, list):
            raise ValueError("membership source proposal has no item list")

        proposal_rows = [_mapping(item, "proposal item") for item in proposal_items]
        proposal_ids = _openalex_ids(
            [row.get("openalex_id") for row in proposal_rows],
            expected_count=100,
            name="source proposal",
        )
        proposal_records = {cast(str, row["openalex_id"]): row for row in proposal_rows}
        decisions_value = raw.get("decisions")
        if not isinstance(decisions_value, list):
            raise ValueError("membership decision has no decisions list")
        decision_rows = [
            _mapping(item, "membership decision item") for item in decisions_value
        ]
        if any(row.get("decision") != "include" for row in decision_rows):
            raise ValueError(
                "approved 100-paper decision must include each selected item"
            )
        decision_ids = _openalex_ids(
            [row.get("openalex_id") for row in decision_rows],
            expected_count=100,
            name="membership decision",
        )
        if proposal_ids != decision_ids:
            raise ValueError("membership decisions do not match the source proposal")

        titles: dict[str, str] = {}
        years: dict[str, int] = {}
        reasons: dict[str, str] = {}
        selected_sources: dict[str, SelectedSourceRoute] = {}
        for row in decision_rows:
            openalex_id = cast(str, row["openalex_id"])
            proposal_row = proposal_records[openalex_id]
            title = proposal_row.get("title")
            year = proposal_row.get("publication_year")
            reason = row.get("reason")
            if (
                not isinstance(title, str)
                or not title.strip()
                or isinstance(year, bool)
                or not isinstance(year, int)
                or not isinstance(reason, str)
                or not reason.strip()
                or row.get("title") != title
                or row.get("publication_year") != year
                or reason != proposal_row.get("selection_rationale")
            ):
                raise ValueError("membership decision metadata does not match proposal")
            source_name = proposal_row.get("source_name")
            source_url = proposal_row.get("source_url")
            version = proposal_row.get("version")
            terms_url = proposal_row.get("terms_url")
            license_id = proposal_row.get("license_id")
            pool = proposal_row.get("pool")
            if (
                not isinstance(source_name, str)
                or not source_name.strip()
                or not isinstance(source_url, str)
                or not source_url.startswith("https://")
                or not isinstance(version, str)
                or not version.strip()
                or (terms_url is not None and not isinstance(terms_url, str))
                or not isinstance(license_id, str)
                or not license_id.strip()
                or not isinstance(pool, str)
                or not pool.strip()
            ):
                raise ValueError("membership proposal has an invalid selected source")
            titles[openalex_id] = title
            years[openalex_id] = year
            reasons[openalex_id] = reason
            selected_sources[openalex_id] = SelectedSourceRoute(
                source_name=source_name,
                source_url=source_url,
                version=version,
                terms_url=terms_url,
                license_id=license_id,
                pool=pool,
            )

        return cls(
            identity="sha256:" + hashlib.sha256(decision_bytes).hexdigest(),
            selected_openalex_ids=frozenset(decision_ids),
            selected_titles=MappingProxyType(titles),
            publication_years=MappingProxyType(years),
            selection_reasons=MappingProxyType(reasons),
            selected_sources=MappingProxyType(selected_sources),
        )

    def with_source_route_review(self, review_path: Path) -> MembershipDecision:
        """Apply narrowly validated canonical ACL terms links from a review record."""
        try:
            review_bytes = review_path.read_bytes()
            raw = json.loads(review_bytes)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("source route review file cannot be read") from error
        review = _mapping(raw, "source route review")
        if review.get("schema_version") != 1 or isinstance(
            review.get("schema_version"), bool
        ):
            raise ValueError("unsupported source route review schema")
        if review.get("record_type") != "phase1_100_source_route_review":
            raise ValueError("file is not a Phase 1 100-paper source route review")
        if review.get("membership_decision_id") != self.identity:
            raise ValueError(
                "source route review belongs to another membership decision"
            )
        reviewer = review.get("reviewer")
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("source route review has no reviewer")
        raw_corrections = review.get("canonical_link_corrections")
        if not isinstance(raw_corrections, list):
            raise ValueError("source route review has no canonical link corrections")

        expected_corrections = {
            openalex_id: route.terms_url
            for openalex_id, route in self.selected_sources.items()
            if route.terms_url is not None
            and route.terms_url.startswith("https://aclanthology.org/https://")
        }
        corrections: dict[str, str] = {}
        for raw_correction in raw_corrections:
            correction = _mapping(raw_correction, "canonical link correction")
            openalex_id = correction.get("openalex_id")
            original = correction.get("original_terms_url")
            canonical = correction.get("canonical_terms_url")
            evidence_url = correction.get("evidence_url")
            if (
                not isinstance(openalex_id, str)
                or openalex_id not in expected_corrections
                or not isinstance(original, str)
                or original != expected_corrections[openalex_id]
                or not isinstance(canonical, str)
                or canonical != _canonical_acl_terms_url(original)
                or not isinstance(evidence_url, str)
                or evidence_url != canonical
                or urlsplit(canonical).hostname != "aclanthology.org"
            ):
                raise ValueError("source route correction is not a canonical ACL link")
            if openalex_id in corrections:
                raise ValueError("source route review repeats a correction")
            corrections[openalex_id] = canonical
        if set(corrections) != set(expected_corrections):
            raise ValueError(
                "source route review does not cover all malformed ACL links"
            )

        expected_arxiv = {
            openalex_id: route
            for openalex_id, route in self.selected_sources.items()
            if urlsplit(route.source_url).hostname == "arxiv.org"
        }
        raw_arxiv_checks = review.get("arxiv_license_checks")
        if not isinstance(raw_arxiv_checks, list):
            raise ValueError("source route review has no arXiv version license checks")
        checked_arxiv: set[str] = set()
        for raw_check in raw_arxiv_checks:
            check = _mapping(raw_check, "arXiv license check")
            openalex_id = check.get("openalex_id")
            if not isinstance(openalex_id, str) or openalex_id not in expected_arxiv:
                raise ValueError("source route review names an unselected arXiv paper")
            route = expected_arxiv[openalex_id]
            if (
                check.get("version") != route.version
                or check.get("version_url") != route.terms_url
                or check.get("source_pdf_url") != route.source_url
                or check.get("license_id") != "cc-by"
                or check.get("license_url")
                != "https://creativecommons.org/licenses/by/4.0/"
                or check.get("review_status") != "verified"
                or openalex_id in checked_arxiv
            ):
                raise ValueError(
                    "arXiv license evidence does not match the selected version"
                )
            checked_arxiv.add(openalex_id)
        if checked_arxiv != set(expected_arxiv):
            raise ValueError(
                "source route review does not cover all selected arXiv versions"
            )

        updated_sources = {
            openalex_id: replace(route, terms_url=corrections[openalex_id])
            if openalex_id in corrections
            else route
            for openalex_id, route in self.selected_sources.items()
        }
        return replace(
            self,
            selected_sources=MappingProxyType(updated_sources),
            source_route_review_identity=(
                "sha256:" + hashlib.sha256(review_bytes).hexdigest()
            ),
        )


def _canonical_acl_terms_url(original: str) -> str:
    legacy_prefix = "https://aclanthology.org/https://www.aclweb.org/anthology/"
    if original.startswith(legacy_prefix):
        return original.replace(legacy_prefix, "https://aclanthology.org/", 1)
    duplicate_prefix = "https://aclanthology.org/https://"
    if original.startswith(duplicate_prefix):
        return original.removeprefix("https://aclanthology.org/")
    raise ValueError("source route correction is not a known malformed ACL URL")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return cast(Mapping[str, object], value)


def _openalex_ids(values: list[object], *, expected_count: int, name: str) -> set[str]:
    if len(values) != expected_count:
        raise ValueError(f"{name} must contain exactly {expected_count} papers")
    ids: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not _OPENALEX_ID.fullmatch(value):
            raise ValueError(f"{name} contains an invalid OpenAlex ID")
        ids.add(value)
    if len(ids) != expected_count:
        raise ValueError(f"{name} contains duplicate OpenAlex IDs")
    return ids
