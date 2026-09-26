"""Canonical external IDs and deterministic document-version preference."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

IdentifierNamespace = Literal["openalex", "doi", "arxiv", "pmid"]
DocumentVersionKind = Literal["published", "preprint", "other", "unknown"]

_OPENALEX_PATTERN = re.compile(r"^W[0-9]+$")
_DOI_PATTERN = re.compile(r"^10\.[0-9]{4,9}/\S+$", re.IGNORECASE)
_ARXIV_PATTERN = re.compile(r"^[0-9]{4}\.[0-9]{4,5}$|^[a-z-]+/[0-9]{7}$", re.IGNORECASE)


def is_valid_paper_id(value: object) -> bool:
    """Return whether a value is a canonical OpenAlex work identifier."""
    return isinstance(value, str) and _OPENALEX_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True)
class ExternalIdentifier:
    namespace: IdentifierNamespace
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("external identifier must be a non-empty string")
        normalized = self._normalize(self.namespace, self.value)
        object.__setattr__(self, "value", normalized)

    @property
    def normalized_value(self) -> str:
        return self.value

    @staticmethod
    def _normalize(namespace: IdentifierNamespace, value: str) -> str:
        normalized = value.strip()
        if namespace == "openalex":
            normalized = normalized.removeprefix("https://openalex.org/")
            if not _OPENALEX_PATTERN.fullmatch(normalized):
                raise ValueError("OpenAlex identifiers must be work IDs such as W123")
            return normalized
        if namespace == "doi":
            lowered = normalized.lower()
            for prefix in ("https://doi.org/", "http://doi.org/"):
                if lowered.startswith(prefix):
                    normalized = normalized[len(prefix) :]
                    break
            else:
                if lowered.startswith("doi:"):
                    normalized = normalized[4:]
            normalized = normalized.strip().lower()
            if not _DOI_PATTERN.fullmatch(normalized):
                raise ValueError("DOI must have a valid 10.xxxx/... form")
            return normalized
        if namespace == "arxiv":
            lowered = normalized.lower()
            for prefix in (
                "https://arxiv.org/abs/",
                "http://arxiv.org/abs/",
                "https://arxiv.org/pdf/",
                "http://arxiv.org/pdf/",
            ):
                if lowered.startswith(prefix):
                    normalized = normalized[len(prefix) :]
                    break
            normalized = re.sub(r"\.pdf$", "", normalized, flags=re.IGNORECASE)
            normalized = re.sub(r"v[0-9]+$", "", normalized, flags=re.IGNORECASE)
            if not _ARXIV_PATTERN.fullmatch(normalized):
                raise ValueError("arXiv identifier must be a modern or legacy arXiv ID")
            return normalized.lower()
        if namespace == "pmid":
            lowered = normalized.lower()
            for prefix in (
                "https://pubmed.ncbi.nlm.nih.gov/",
                "http://pubmed.ncbi.nlm.nih.gov/",
            ):
                if lowered.startswith(prefix):
                    normalized = normalized[len(prefix) :].rstrip("/")
                    break
            if not normalized.isdigit():
                raise ValueError("PMID must contain only digits")
            return normalized
        raise ValueError(f"unsupported identifier namespace: {namespace}")


@dataclass(frozen=True)
class DocumentVersion:
    document_id: str
    kind: DocumentVersionKind
    indexing_permitted: bool
    published_at: datetime | None = None
    source_type: str = ""
    version_label: str = ""


def choose_preferred_document_version(
    versions: tuple[DocumentVersion, ...],
) -> DocumentVersion | None:
    """Prefer an index-permitted published copy, then an eligible preprint."""
    eligible = [
        version
        for version in versions
        if version.indexing_permitted and version.kind in {"published", "preprint"}
    ]
    if not eligible:
        return None
    preferred_kind = (
        "published" if any(v.kind == "published" for v in eligible) else "preprint"
    )
    preferred = [version for version in eligible if version.kind == preferred_kind]

    def sort_key(version: DocumentVersion) -> tuple[object, ...]:
        published_at = version.published_at
        if published_at is None:
            date_key: tuple[int, ...] = (1, 0, 0, 0, 0, 0, 0)
        else:
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            published_at = published_at.astimezone(timezone.utc)
            date_key = (
                0,
                -published_at.year,
                -published_at.month,
                -published_at.day,
                -published_at.hour,
                -published_at.minute,
                -published_at.second,
                -published_at.microsecond,
            )
        return (
            *date_key,
            version.source_type,
            version.version_label,
            version.document_id,
        )

    return min(preferred, key=sort_key)
