"""Versioned query/evidence formatting and explicit pair-budget behavior."""

from uuid import UUID

import pytest

from research_platform.ingestion.evidence import (
    ChunkingConfig,
    EvidenceKind,
    ExtractedTable,
    SourceLocation,
    TableCell,
    chunk_table_rows,
)
from research_platform.search.contracts import ComponentScores, EvidenceHit
from research_platform.search.reranker_pairs import (
    DEFAULT_MAX_PAIR_TOKENS,
    RERANKER_PAIR_FORMAT_ID,
    PairBudgetViolation,
    RerankerPairBudgetExceeded,
    RerankerPairFormatError,
    build_reranker_pairs,
)

DOCUMENT_ID = UUID("91a7da33-066d-4c78-838a-413ba2f1b8d4")
EXTRACTION_ID = UUID("6715a62a-fb8c-41d3-812d-3130baf08f0f")


class FixedPairCounter:
    def __init__(self, count: int) -> None:
        self.count = count
        self.calls: list[tuple[str, str]] = []

    def count_pair(self, query: str, evidence_text: str) -> int:
        self.calls.append((query, evidence_text))
        return self.count


def _hit(
    rank: int,
    number: int,
    text: str,
    *,
    kind: EvidenceKind = "text",
) -> EvidenceHit:
    stable_id = f"sha256:{number:064x}"
    return EvidenceHit(
        chunk_id=stable_id,
        source_evidence_ids=(stable_id,),
        paper_id="W100",
        document_id=DOCUMENT_ID,
        document_version="published-2025",
        document_version_kind="published",
        extraction_id=EXTRACTION_ID,
        chunking_configuration_id=None,
        kind=kind,
        source_location=SourceLocation(),
        rank=rank,
        component_scores=ComponentScores(),
        text=text,
    )


def test_pair_format_passes_query_and_evidence_text_verbatim() -> None:
    query = "  Which result is reported?  "
    evidence = "Section text stays byte-for-byte as stored.\n"
    counter = FixedPairCounter(24)
    hit = _hit(1, 1, evidence)

    pairs = build_reranker_pairs(
        query,
        (hit,),
        token_counters={"minilm@revision-a": counter},
    )

    assert len(pairs) == 1
    assert pairs[0].evidence_hit is hit
    assert pairs[0].pair_format_id == RERANKER_PAIR_FORMAT_ID
    assert pairs[0].query == query
    assert pairs[0].evidence_hit.text == evidence
    assert pairs[0].token_counts == (("minilm@revision-a", 24),)
    assert counter.calls == [(query, evidence)]


def test_table_row_group_keeps_caption_units_headers_footnotes_and_values() -> None:
    table = ExtractedTable(
        ordinal=1,
        caption="Latency by method",
        units="milliseconds",
        footnotes=("Lower is better.",),
        header_rows=1,
        cells=(
            TableCell(0, 0, "Method"),
            TableCell(0, 1, "Latency"),
            TableCell(1, 0, "A"),
            TableCell(
                1, 1, "42.1", row_header_cells=((1, 0),), column_header_cells=((0, 1),)
            ),
        ),
        source_location=SourceLocation(page_index_zero_based=7),
    )
    unit = chunk_table_rows(
        table,
        document_id=DOCUMENT_ID,
        extraction_id=EXTRACTION_ID,
        config=ChunkingConfig(10, 0, 1),
    )[0]
    counter = FixedPairCounter(30)

    pair = build_reranker_pairs(
        "Compare methods.",
        (_hit(1, 2, unit.content, kind="table_row_group"),),
        token_counters={"bge@revision-b": counter},
    )[0]

    assert pair.evidence_hit.text == unit.content
    assert "Caption: Latency by method" in pair.evidence_hit.text
    assert "Units: milliseconds" in pair.evidence_hit.text
    assert "Method | Latency" in pair.evidence_hit.text
    assert "A | 42.1" in pair.evidence_hit.text
    assert "Footnotes: Lower is better." in pair.evidence_hit.text


def test_exact_limit_is_accepted_and_candidate_order_is_preserved() -> None:
    hits = (_hit(8, 8, "second in list"), _hit(3, 3, "first in list"))
    counters = {
        "bge@revision-b": FixedPairCounter(DEFAULT_MAX_PAIR_TOKENS),
        "minilm@revision-a": FixedPairCounter(DEFAULT_MAX_PAIR_TOKENS),
    }

    pairs = build_reranker_pairs(
        "query",
        hits,
        token_counters=counters,
    )

    assert [pair.evidence_hit.chunk_id for pair in pairs] == [
        hit.chunk_id for hit in hits
    ]
    assert [pair.evidence_hit.rank for pair in pairs] == [8, 3]
    assert [pair.token_counts for pair in pairs] == [
        (
            ("bge@revision-b", DEFAULT_MAX_PAIR_TOKENS),
            ("minilm@revision-a", DEFAULT_MAX_PAIR_TOKENS),
        )
    ] * 2


def test_over_budget_for_any_comparison_tokenizer_rejects_the_whole_pair_set() -> None:
    hits = (
        _hit(1, 1, "fits"),
        _hit(2, 2, "does not fit BGE"),
    )

    class SelectiveBgeCounter:
        def count_pair(self, query: str, evidence_text: str) -> int:
            return 513 if evidence_text == "does not fit BGE" else 400

    counters = {
        "minilm@revision-a": FixedPairCounter(400),
        "bge@revision-b": SelectiveBgeCounter(),
    }

    with pytest.raises(RerankerPairBudgetExceeded) as error:
        build_reranker_pairs(
            "query",
            hits,
            token_counters=counters,
            maximum_pair_tokens=512,
        )

    assert error.value.violations == (
        PairBudgetViolation(
            chunk_id=hits[1].chunk_id,
            token_counts=(("bge@revision-b", 513), ("minilm@revision-a", 400)),
            maximum_pair_tokens=512,
        ),
    )


def test_empty_candidate_set_is_an_empty_pair_set() -> None:
    assert (
        build_reranker_pairs(
            "query",
            (),
            token_counters={"minilm@revision-a": FixedPairCounter(2)},
        )
        == ()
    )


@pytest.mark.parametrize(
    ("query", "counters", "message"),
    [
        ("  ", {"minilm": FixedPairCounter(2)}, "query text"),
        ("query", {}, "at least one tokenizer"),
        ("query", {" ": FixedPairCounter(2)}, "identifiers"),
        ("query", {"minilm": object()}, "implement count_pair"),
    ],
)
def test_invalid_pair_inputs_fail_closed(
    query: str,
    counters: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(RerankerPairFormatError, match=message):
        build_reranker_pairs(
            query,
            (_hit(1, 1, "evidence"),),
            token_counters=counters,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("count", [0, -1, True, 1.5])
def test_invalid_tokenizer_counts_fail_closed(count: object) -> None:
    class InvalidCounter:
        def count_pair(self, query: str, evidence_text: str) -> object:
            return count

    with pytest.raises(RerankerPairFormatError, match="invalid pair length"):
        build_reranker_pairs(
            "query",
            (_hit(1, 1, "evidence"),),
            token_counters={"minilm@revision-a": InvalidCounter()},  # type: ignore[dict-item]
        )


def test_duplicate_candidate_ids_or_original_ranks_are_rejected() -> None:
    first = _hit(1, 1, "first")
    duplicate_id = _hit(2, 1, "duplicate")
    duplicate_rank = _hit(1, 2, "duplicate rank")
    counters = {"minilm@revision-a": FixedPairCounter(10)}

    with pytest.raises(RerankerPairFormatError, match="chunk IDs"):
        build_reranker_pairs("query", (first, duplicate_id), token_counters=counters)
    with pytest.raises(RerankerPairFormatError, match="ranks"):
        build_reranker_pairs("query", (first, duplicate_rank), token_counters=counters)
