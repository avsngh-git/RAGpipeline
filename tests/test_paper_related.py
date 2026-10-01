"""Unit tests for deterministic related-paper ranking."""

import pytest

from research_platform.search.paper_related import (
    RelatedPaper,
    RelationKind,
    rank_related,
)


def _paper(
    paper_id: str,
    *,
    shared: int,
    co_cited: int,
) -> RelatedPaper:
    relations = tuple(
        kind
        for kind, count in (
            (RelationKind.SHARED_REFERENCES, shared),
            (RelationKind.CO_CITED, co_cited),
        )
        if count > 0
    )
    return RelatedPaper(
        paper_id=paper_id,
        title=None,
        publication_year=None,
        shared_reference_count=shared,
        co_citation_count=co_cited,
        score=shared + co_cited,
        relations=relations,
    )


def test_rank_orders_by_score_then_shared_then_id() -> None:
    rows = (
        _paper("W4", shared=1, co_cited=2),
        _paper("W3", shared=2, co_cited=1),
        _paper("W2", shared=3, co_cited=0),
        _paper("W1", shared=1, co_cited=2),
    )

    ranked = rank_related(rows, limit=10)

    assert [row.paper_id for row in ranked] == ["W2", "W3", "W1", "W4"]


def test_rank_applies_limit() -> None:
    rows = (_paper("W2", shared=1, co_cited=0), _paper("W1", shared=2, co_cited=0))

    assert [row.paper_id for row in rank_related(rows, limit=1)] == ["W1"]


def test_relations_list_only_positive_kinds() -> None:
    paper = _paper("W1", shared=1, co_cited=0)

    assert paper.relations == (RelationKind.SHARED_REFERENCES,)

    with pytest.raises(ValueError, match="positive relation kinds"):
        RelatedPaper(
            paper_id="W2",
            title=None,
            publication_year=None,
            shared_reference_count=0,
            co_citation_count=1,
            score=1,
            relations=(RelationKind.SHARED_REFERENCES, RelationKind.CO_CITED),
        )
