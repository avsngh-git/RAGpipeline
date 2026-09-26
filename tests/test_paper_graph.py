"""Checks snapshot-aware one-hop graph reads and keyset pagination."""

import asyncio
from uuid import UUID

import pytest

from research_platform.search.paper_graph import (
    CitationDirection,
    CitationEndpointStatus,
    CitationGraphCursor,
    CitationGraphReader,
)
from research_platform.search.paper_reads import PaperReadStatus, SnapshotNotFound

SNAPSHOT_ID = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Connection:
    def __init__(
        self, source: dict[str, object], edges: list[dict[str, object]]
    ) -> None:
        self.source = source
        self.edges = edges
        self.source_query: str | None = None
        self.source_arguments: tuple[object, ...] = ()
        self.edge_query: str | None = None
        self.edge_arguments: tuple[object, ...] = ()

    def transaction(self, **_kwargs: object) -> _Transaction:
        return _Transaction()

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, object]:
        self.source_query = query
        self.source_arguments = arguments
        return self.source

    async def fetch(self, query: str, *arguments: object) -> list[dict[str, object]]:
        self.edge_query = query
        self.edge_arguments = arguments
        return self.edges


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Pool:
    def __init__(
        self, source: dict[str, object], edges: list[dict[str, object]]
    ) -> None:
        self.connection = _Connection(source, edges)

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


def _source(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "snapshot_exists": True,
        "resolved_count": 1,
        "local_paper_id": "W123",
        "snapshot_paper_id": "W123",
    }
    row.update(overrides)
    return row


def _resolved_edge(
    paper_id: str, status: str, title: str | None, source: str = "openalex"
) -> dict[str, object]:
    return {
        "endpoint_kind": "paper",
        "endpoint_identifier": paper_id,
        "endpoint_status": status,
        "title": title,
        "publication_year": 2024,
        "external_namespace": None,
        "external_identifier": None,
        "edge_source": source,
    }


def _unresolved_edge(
    identifier: str, namespace: str = "openalex", source: str = "openalex"
) -> dict[str, object]:
    return {
        "endpoint_kind": "external",
        "endpoint_identifier": f"{namespace}:{identifier}",
        "endpoint_status": "unresolved",
        "title": None,
        "publication_year": None,
        "external_namespace": namespace,
        "external_identifier": identifier,
        "edge_source": source,
    }


def test_references_paginate_stably_and_mark_out_of_snapshot_endpoints() -> None:
    first_pool = _Pool(
        _source(),
        [
            _unresolved_edge("W999"),
            _resolved_edge("W456", "outside_snapshot", "Outside paper"),
        ],
    )

    first_page = asyncio.run(
        CitationGraphReader(first_pool).read_one_hop(
            SNAPSHOT_ID, "W123", CitationDirection.REFERENCES, limit=1
        )
    )

    assert first_page.source_status is PaperReadStatus.IN_SNAPSHOT
    assert first_page.edges[0].endpoint.status is CitationEndpointStatus.UNRESOLVED
    assert first_page.edges[0].endpoint.external_identifier == "W999"
    assert first_page.edges[0].endpoint.title is None
    assert first_page.has_more is True
    assert first_page.next_cursor is not None
    assert first_page.next_cursor.endpoint_kind == "external"

    second_pool = _Pool(
        _source(), [_resolved_edge("W456", "outside_snapshot", "Outside paper")]
    )
    second_page = asyncio.run(
        CitationGraphReader(second_pool).read_one_hop(
            SNAPSHOT_ID,
            "W123",
            CitationDirection.REFERENCES,
            limit=1,
            cursor=first_page.next_cursor,
        )
    )

    assert (
        second_page.edges[0].endpoint.status is CitationEndpointStatus.OUTSIDE_SNAPSHOT
    )
    assert second_page.edges[0].endpoint.title == "Outside paper"
    assert second_page.has_more is False
    assert second_pool.connection.edge_arguments[2:5] == (
        "external",
        "openalex:W999",
        "openalex",
    )
    assert "chunks" not in first_pool.connection.edge_query
    assert "evidence_units" not in first_pool.connection.edge_query


def test_incoming_citations_describe_locally_observed_coverage() -> None:
    pool = _Pool(
        _source(snapshot_paper_id=None),
        [_resolved_edge("W456", "in_snapshot", "Citing paper")],
    )

    page = asyncio.run(
        CitationGraphReader(pool).read_one_hop(
            SNAPSHOT_ID, "W123", CitationDirection.CITATIONS
        )
    )

    assert page.source_status is PaperReadStatus.OUTSIDE_SNAPSHOT
    assert page.edges[0].endpoint.status is CitationEndpointStatus.IN_SNAPSHOT
    assert "not a complete global citation list" in page.coverage_note
    assert "source" in pool.connection.edge_query


def test_unknown_paper_returns_empty_page_and_missing_snapshot_errors() -> None:
    unknown_pool = _Pool(
        _source(
            resolved_count=0,
            local_paper_id=None,
            snapshot_paper_id=None,
        ),
        [],
    )
    unknown = asyncio.run(
        CitationGraphReader(unknown_pool).read_one_hop(
            SNAPSHOT_ID, "W123", CitationDirection.REFERENCES
        )
    )
    assert unknown.source_status is PaperReadStatus.UNKNOWN
    assert unknown.edges == ()
    assert unknown_pool.connection.edge_query is None

    missing_pool = _Pool(_source(snapshot_exists=False), [])
    with pytest.raises(SnapshotNotFound, match="snapshot does not exist"):
        asyncio.run(
            CitationGraphReader(missing_pool).read_one_hop(
                SNAPSHOT_ID, "W123", CitationDirection.REFERENCES
            )
        )


def test_cursor_is_bound_to_snapshot_paper_and_direction() -> None:
    pool = _Pool(_source(), [])
    cursor = CitationGraphCursor(
        snapshot_id=SNAPSHOT_ID,
        paper_id="W123",
        direction=CitationDirection.CITATIONS,
        endpoint_kind="paper",
        endpoint_identifier="W456",
        edge_source="openalex",
    )

    with pytest.raises(ValueError, match="cursor does not match"):
        asyncio.run(
            CitationGraphReader(pool).read_one_hop(
                SNAPSHOT_ID, "W123", CitationDirection.REFERENCES, cursor=cursor
            )
        )

    assert pool.connection.source_query is None


def test_page_size_and_noncanonical_ids_are_rejected() -> None:
    pool = _Pool(_source(), [])
    reader = CitationGraphReader(pool)

    with pytest.raises(ValueError, match="between 1 and 100"):
        asyncio.run(
            reader.read_one_hop(
                SNAPSHOT_ID, "W123", CitationDirection.REFERENCES, limit=101
            )
        )
    with pytest.raises(ValueError, match="canonical OpenAlex work ID"):
        asyncio.run(
            reader.read_one_hop(SNAPSHOT_ID, "123", CitationDirection.REFERENCES)
        )
