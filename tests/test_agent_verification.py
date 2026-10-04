"""Code checks that keep a claim only when its quote grounds it in the cited passage."""

from __future__ import annotations

import pytest

from research_platform.agents.verification import (
    content_overlap,
    normalize,
    verify_claim,
)

_PROSE = (
    "We find that retrieval-aug- mented generation with a cross-encoder reranker "
    "improves exact match by 4.5 points on NQ. Results on 9k questions follow."
)
_QUOTE = "retrieval-augmented generation with a cross-encoder reranker improves exact match by 4.5 points on NQ."
_TABLE = (
    "Caption: Table 7: Results on two datasets.\n"
    "Group: unsupervised\n"
    "Row: Method: SparseX; Dataset A — mAP: 31.40, nDCG@10: 52.70; Dataset B — mAP: 29.10\n"
    "Row: Method: DenseY; Dataset A — mAP: 24.60, nDCG@10: 45.20; Dataset B — mAP: 24.30\n"
    "Row: Method: DenseY + SparseX; Dataset A — mAP: 53.80, nDCG@10: 74.10"
)


def test_exact_prose_quote_and_close_claim_pass() -> None:
    checks = verify_claim(
        "A cross-encoder reranker improves exact match by 4.5 points on NQ.",
        _QUOTE,
        _PROSE,
    )

    assert checks.passed


def test_prose_quote_may_differ_slightly() -> None:
    near = "retrieval augmented generation with the cross encoder reranker improves exact match by 4.5 points on NQ"

    checks = verify_claim(
        "The reranker improves exact match by 4.5 points.", near, _PROSE
    )

    assert checks.quote_found


@pytest.mark.parametrize(
    "quote",
    [
        "dense retrieval beats sparse retrieval on every benchmark we tried",
        "improves exact",
    ],
    ids=["absent", "too-short"],
)
def test_quote_absent_or_too_short_fails(quote: str) -> None:
    assert not verify_claim(
        "Dense retrieval beats sparse retrieval.", quote, _PROSE
    ).quote_found


def test_claim_far_from_its_quote_fails_overlap() -> None:
    checks = verify_claim(
        "Dense encoders outperform sparse baselines on multilingual benchmarks.",
        _QUOTE,
        _PROSE,
    )

    assert checks.quote_found
    assert not checks.words_from_quote
    assert not checks.passed


def test_numbers_must_come_from_the_quote() -> None:
    changed = verify_claim(
        "The reranker improves exact match by 5.4 points.", _QUOTE, _PROSE
    )
    thousands = verify_claim(
        "Results cover 9,000 questions.", "Results on 9k questions follow.", _PROSE
    )

    assert not changed.numbers_from_quote
    assert thousands.numbers_from_quote


def test_intensifier_must_come_from_the_quote_but_superlatives_may_paraphrase() -> None:
    intensified = verify_claim(
        "A cross-encoder reranker significantly improves exact match by 4.5 points on NQ.",
        _QUOTE,
        _PROSE,
    )
    superlative = verify_claim(
        "The best configuration improves exact match by 4.5 points on NQ.",
        _QUOTE,
        _PROSE,
    )

    assert not intensified.intensifiers_from_quote
    assert superlative.intensifiers_from_quote


def test_handle_in_claim_text_fails() -> None:
    checks = verify_claim(
        "A cross-encoder reranker improves exact match by 4.5 points on NQ [E3].",
        _QUOTE,
        _PROSE,
    )

    assert not checks.no_handles_in_text


def test_full_table_row_quote_passes() -> None:
    checks = verify_claim(
        "SparseX reached an nDCG@10 of 52.70 on Dataset A.",
        "Row: Method: SparseX; Dataset A — mAP: 31.40, nDCG@10: 52.70",
        _TABLE,
    )

    assert checks.passed


def test_table_quote_must_match_exactly() -> None:
    checks = verify_claim(
        "SparseX reached an nDCG@10 of 52.71 on Dataset A.",
        "Method: SparseX; Dataset A — mAP: 31.40, nDCG@10: 52.71",
        _TABLE,
    )

    assert not checks.quote_found


def test_table_quote_without_its_row_label_fails() -> None:
    checks = verify_claim(
        "DenseY reached an nDCG@10 of 52.70 on Dataset A.",
        "Dataset A — mAP: 31.40, nDCG@10: 52.70",
        _TABLE,
    )

    assert checks.quote_found
    assert not checks.quote_names_its_row


def test_claim_naming_another_row_fails() -> None:
    checks = verify_claim(
        "DenseY + SparseX reached an mAP of 24.60 on Dataset A.",
        "Method: DenseY; Dataset A — mAP: 24.60",
        _TABLE,
    )

    assert checks.quote_names_its_row
    assert not checks.no_other_row_named


def test_normalize_keeps_decimal_points_and_rejoins_hyphenation() -> None:
    assert (
        normalize("Score: 0.253. Retrieval-aug- mented.")
        == "score 0.253 retrieval augmented"
    )
    assert normalize("0.253") != normalize("0.254")


def test_content_overlap_ignores_stopwords() -> None:
    assert content_overlap("The reranker is good", "a good reranker") == 1.0
    assert content_overlap("", "anything") == 0.0
