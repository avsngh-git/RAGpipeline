"""Checksum-bound exclusions for third-party content inside selected PDFs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import cast
from uuid import UUID


@dataclass(frozen=True)
class SourceContentReview:
    """A reviewed, exact-file map of one-based PDF pages to omit from evidence."""

    identity: str
    membership_decision_id: str
    excluded_source_pages_by_document: Mapping[UUID, frozenset[int]]
    reviewed_documents: Mapping[UUID, str]

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        membership_decision_id: str,
        source_route_review_id: str,
        document_ids_by_paper: Mapping[str, UUID],
        input_fingerprints_by_document: Mapping[UUID, str],
    ) -> SourceContentReview:
        """Load the narrow RadioRAG supplement review against current job inputs."""
        try:
            content = path.read_bytes()
            raw = json.loads(content)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("source content review file cannot be read") from error
        if not isinstance(raw, Mapping):
            raise ValueError("source content review must be a JSON object")
        if raw.get("schema_version") != 1 or isinstance(
            raw.get("schema_version"), bool
        ):
            raise ValueError("unsupported source content review schema")
        if raw.get("record_type") != "phase1_100_source_content_review":
            raise ValueError("file is not a Phase 1 source content review")
        if raw.get("membership_decision_id") != membership_decision_id:
            raise ValueError("source content review belongs to another membership")
        if raw.get("source_route_review_id") != source_route_review_id:
            raise ValueError("source content review belongs to another route review")
        reviewer = raw.get("reviewer")
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("source content review has no reviewer")
        entries = raw.get("exclusions")
        if not isinstance(entries, list) or len(entries) != 1:
            raise ValueError(
                "source content review must contain one reviewed exclusion"
            )

        entry_value = entries[0]
        if not isinstance(entry_value, Mapping):
            raise ValueError("source content exclusion must be a JSON object")
        entry = cast(Mapping[str, object], entry_value)
        paper_id = entry.get("openalex_id")
        expected_document_id = document_ids_by_paper.get("W4402853403")
        if paper_id != "W4402853403" or expected_document_id is None:
            raise ValueError("source content review names an unsupported paper")
        try:
            document_id = UUID(str(entry.get("document_id")))
        except (ValueError, TypeError) as error:
            raise ValueError(
                "source content review has an invalid document ID"
            ) from error
        if document_id != expected_document_id:
            raise ValueError("source content review names a different document version")

        fingerprint = input_fingerprints_by_document.get(document_id)
        source_sha256 = entry.get("source_pdf_sha256")
        if (
            not isinstance(fingerprint, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint)
            or not isinstance(source_sha256, str)
            or fingerprint != f"sha256:{source_sha256}"
        ):
            raise ValueError("source content review does not match the PDF checksum")

        page_count = entry.get("source_page_count")
        page_values = entry.get("excluded_page_numbers")
        if (
            isinstance(page_count, bool)
            or not isinstance(page_count, int)
            or page_count != 39
            or not isinstance(page_values, list)
            or any(
                isinstance(page, bool) or not isinstance(page, int)
                for page in page_values
            )
            or page_values != list(range(21, 36))
            or max(page_values) > page_count
        ):
            raise ValueError("source content review has unsupported page exclusions")
        if (
            entry.get("source_route")
            != "https://content.openalex.org/works/W4402853403.pdf"
            or entry.get("source_version_url") != "https://arxiv.org/abs/2407.15621v3"
            or entry.get("license_id") != "cc-by"
        ):
            raise ValueError("source content review does not match the selected source")
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("source content exclusion has no review reason")

        return cls(
            identity="sha256:" + hashlib.sha256(content).hexdigest(),
            membership_decision_id=membership_decision_id,
            excluded_source_pages_by_document=MappingProxyType(
                {document_id: frozenset(page_values)}
            ),
            reviewed_documents=MappingProxyType({document_id: source_sha256}),
        )
