"""Checks bounded, snapshot-aware public paper reads."""

import asyncio
from uuid import UUID

import pytest

from research_platform.search.paper_reads import (
    MetadataAvailability,
    PaperIdentityConflict,
    PaperReadStatus,
    SnapshotNotFound,
    SnapshotPaperReader,
)

SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")
DOCUMENT_ID = UUID("91a7da33-066d-4c78-838a-413ba2f1b8d4")


class _Connection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.query: str | None = None
        self.arguments: tuple[object, ...] = ()

    async def fetch(self, query: str, *arguments: object) -> list[dict[str, object]]:
        self.query = query
        self.arguments = arguments
        return self.rows


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Pool:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.connection = _Connection(rows)

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "snapshot_exists": True,
        "resolved_count": 1,
        "local_paper_id": "W123",
        "title": "A scientific paper",
        "publication_year": 2024,
        "abstract_inverted_index": {"Evidence": [0], "matters.": [1]},
        "snapshot_paper_id": "W123",
        "document_id": DOCUMENT_ID,
        "document_version": "published-version-2024-01",
        "document_version_kind": "published",
    }
    row.update(overrides)
    return row


def test_reads_selected_metadata_and_actual_document_version() -> None:
    pool = _Pool([_row()])

    result = asyncio.run(SnapshotPaperReader(pool).read_paper(SNAPSHOT_ID, "W123"))

    assert result.status is PaperReadStatus.IN_SNAPSHOT
    assert result.document_id == DOCUMENT_ID
    assert result.document_version == "published-version-2024-01"
    assert result.document_version_kind == "published"
    assert result.metadata_availability == MetadataAvailability(True, True, True)
    assert pool.connection.arguments == (SNAPSHOT_ID, "W123")


def test_distinguishes_known_paper_outside_snapshot_from_unknown_id() -> None:
    outside_pool = _Pool([_row(snapshot_paper_id=None, document_id=None)])
    unknown_pool = _Pool(
        [
            _row(
                resolved_count=0,
                local_paper_id=None,
                title=None,
                publication_year=None,
                abstract_inverted_index=None,
                snapshot_paper_id=None,
                document_id=None,
                document_version=None,
                document_version_kind=None,
            )
        ]
    )

    outside = asyncio.run(
        SnapshotPaperReader(outside_pool).read_paper(SNAPSHOT_ID, "W123")
    )
    unknown = asyncio.run(
        SnapshotPaperReader(unknown_pool).read_paper(SNAPSHOT_ID, "W123")
    )

    assert outside.status is PaperReadStatus.OUTSIDE_SNAPSHOT
    assert outside.title == "A scientific paper"
    assert outside.document_version is None
    assert outside.metadata_availability == MetadataAvailability(True, True, True)
    assert unknown.status is PaperReadStatus.UNKNOWN
    assert unknown.title is None
    assert unknown.metadata_availability == MetadataAvailability(False, False, False)


def test_reports_missing_snapshot_before_classifying_paper() -> None:
    pool = _Pool(
        [
            _row(
                snapshot_exists=False,
                resolved_count=0,
                local_paper_id=None,
                title=None,
                publication_year=None,
                abstract_inverted_index=None,
                snapshot_paper_id=None,
                document_id=None,
                document_version=None,
                document_version_kind=None,
            )
        ]
    )

    with pytest.raises(SnapshotNotFound, match="snapshot does not exist"):
        asyncio.run(SnapshotPaperReader(pool).read_paper(SNAPSHOT_ID, "W123"))


def test_rejects_ambiguous_public_id_resolution() -> None:
    pool = _Pool([_row(resolved_count=2), _row(local_paper_id="other-local-id")])

    with pytest.raises(PaperIdentityConflict, match="multiple local paper records"):
        asyncio.run(SnapshotPaperReader(pool).read_paper(SNAPSHOT_ID, "W123"))


def test_paper_read_query_is_single_and_bounded_without_evidence_text() -> None:
    pool = _Pool([_row()])

    asyncio.run(SnapshotPaperReader(pool).read_paper(SNAPSHOT_ID, "W123"))

    assert pool.connection.query is not None
    assert "LIMIT 2" in pool.connection.query
    assert "snapshot_items" in pool.connection.query
    assert "chunks" not in pool.connection.query
    assert "evidence_units" not in pool.connection.query
    assert "content" not in pool.connection.query
    assert "abstract_inverted_index" in pool.connection.query
    assert "paper.metadata," not in pool.connection.query


def test_rejects_noncanonical_public_id_before_querying() -> None:
    pool = _Pool([_row()])

    with pytest.raises(ValueError, match="canonical OpenAlex work ID"):
        asyncio.run(
            SnapshotPaperReader(pool).read_paper(
                SNAPSHOT_ID, "https://openalex.org/W123"
            )
        )

    assert pool.connection.query is None
