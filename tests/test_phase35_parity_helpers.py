"""Pure comparison helpers for the Phase 3.5 lexical parity check (P35-15)."""

from __future__ import annotations

from scripts.phase35_lexical_parity import (
    compare_rank_lists,
    compare_responses,
    sampled_queries,
)


def test_rank_lists_equal_with_tolerance() -> None:
    expected = [("a", 3.0), ("b", 2.0)]

    assert compare_rank_lists(
        expected, [("a", 3.00001), ("b", 2.0)], rel_tol=1e-4
    ).equal
    assert (
        compare_rank_lists(expected, [("a", 3.1), ("b", 2.0)], rel_tol=1e-4).kind
        == "score"
    )
    assert (
        compare_rank_lists(expected, [("b", 2.0), ("a", 3.0)], rel_tol=1e-4).kind
        == "order"
    )
    assert compare_rank_lists(expected, [("a", 3.0)], rel_tol=1e-4).kind == "length"
    assert compare_rank_lists([], [], rel_tol=1e-4).equal


def test_mismatch_classification_boundary_tie() -> None:
    expected = [("a", 3.0), ("b", 1.0), ("c", 1.0)]

    swapped = [("a", 3.0), ("c", 1.0), ("b", 1.0)]
    assert compare_rank_lists(expected, swapped, rel_tol=1e-4).kind == "tie_order"
    crossed = [("a", 3.0), ("b", 1.0), ("d", 1.0)]
    assert compare_rank_lists(expected, crossed, rel_tol=1e-4).kind == "boundary_tie"
    other = [("a", 3.0), ("d", 2.0), ("c", 1.0)]
    assert compare_rank_lists(expected, other, rel_tol=1e-4).kind == "order"


def test_sampled_query_generation_is_deterministic() -> None:
    chunks = [
        (f"c{index:03d}", " ".join(f"w{n}" for n in range(20))) for index in range(50)
    ]

    first = sampled_queries(chunks, count=10, seed=35, tokens=12)
    again = sampled_queries(list(reversed(chunks)), count=10, seed=35, tokens=12)

    assert first == again
    assert len(first) == 10 and len({chunk for chunk, _ in first}) == 10
    assert all(len(query.split()) == 12 for _, query in first)
    assert sampled_queries(chunks, count=10, seed=36, tokens=12) != first
    assert sampled_queries(chunks[:3], count=10, seed=35, tokens=12) == sampled_queries(
        chunks[:3], count=3, seed=35, tokens=12
    )


def test_response_differences_name_the_changed_component() -> None:
    def record(lexical: float, reranker: float) -> dict[str, object]:
        return {
            "effective_mode": "reranked",
            "eligible_count": 5,
            "result_status": "ranked_candidates",
            "truncated": False,
            "omitted_count": 0,
            "warnings": [],
            "hits": [
                {
                    "id": "e1",
                    "rank": 1,
                    "scores": {
                        "lexical": [1, lexical],
                        "dense": [2, 0.5],
                        "fusion": [1, 0.1],
                        "reranker": [1, reranker],
                    },
                }
            ],
        }

    assert compare_responses(record(10.0, 0.9), record(10.00001, 0.9)) == []
    assert compare_responses(record(10.0, 0.9), record(10.0, 0.91)) == [
        "reranker_score"
    ]
    assert compare_responses(record(10.0, 0.9), record(11.0, 0.9)) == ["lexical_score"]


def test_builtin_document_length_inverts_the_bm25_weight() -> None:
    from scripts.phase35_builtin_bm25_comparison import document_length

    def weight(length: int, average: float) -> float:
        return 2.2 / (1 + 1.2 * (0.25 + 0.75 * length / average))

    assert abs(document_length([weight(37, 256.0), 3.0], 256.0) - 37) < 1e-9
    assert abs(document_length([weight(5, 43.3)], 43.3) - 5) < 1e-9
    assert document_length([], 256.0) == 0.0


def test_builtin_document_length_finds_repeated_terms() -> None:
    from scripts.phase35_builtin_bm25_comparison import document_length

    def weight(tf: int, length: int, average: float) -> float:
        return 2.2 * tf / (tf + 1.2 * (0.25 + 0.75 * length / average))

    # Every term occurs twice: four tokens, two distinct terms.
    assert abs(document_length([weight(2, 4, 30.0)] * 2, 30.0) - 4) < 1e-9


def test_tie_aware_match_allows_only_equal_score_reordering() -> None:
    from scripts.phase35_lexical_parity import tie_aware_match

    expected = [("a", 3.0), ("b", 1.0), ("c", 1.0)]
    ulp_noise = [("a", 3.0), ("c", 1.0000001), ("b", 1.0)]
    real_swap = [("a", 3.0), ("c", 1.00001), ("b", 1.0)]

    assert tie_aware_match(expected, ulp_noise, counts_equal=True)
    assert tie_aware_match(
        expected, [("a", 3.0), ("b", 1.0), ("d", 1.0)], counts_equal=True
    )
    assert not tie_aware_match(expected, real_swap, counts_equal=True)
    assert not tie_aware_match(expected, expected, counts_equal=False)
