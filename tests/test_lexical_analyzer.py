from __future__ import annotations

import pytest

from research_platform.search.lexical_analyzer import (
    ANALYZER_ID,
    ANALYZER_REVISION,
    NORMALIZATION_REVISION,
    TOKEN_PATTERN_REVISION,
    tokenize_scientific_english,
)


def test_scientific_analyzer_has_explicit_version_identity() -> None:
    assert ANALYZER_ID == "scientific-en"
    assert ANALYZER_REVISION == "v1"
    assert NORMALIZATION_REVISION == "unicode-nfc-casefold-dashes-micro-v1"
    assert TOKEN_PATTERN_REVISION == "scientific-compound-number-operator-v1"


def test_retains_casefolded_acronyms_one_character_terms_and_stopwords() -> None:
    tokens = tokenize_scientific_english("RAG, LLM, x, a, not without")

    assert tokens == ("rag", "llm", "x", "a", "not", "without")


def test_emits_technical_compound_and_component_tokens() -> None:
    tokens = tokenize_scientific_english("e5-small-v2 top-k μg/mL C++")

    assert "e5-small-v2" in tokens
    assert {
        "e5",
        "small",
        "v2",
        "top-k",
        "top",
        "k",
        "μg/ml",
        "μg",
        "ml",
        "c++",
        "c",
    } <= set(tokens)


def test_preserves_numeric_forms_and_components() -> None:
    tokens = tokenize_scientific_english("0.05 95% -1,200.5 1/2")

    assert "0.05" in tokens
    assert "95%" in tokens
    assert "-1,200.5" in tokens
    assert "1/2" in tokens
    assert {"0", "05", "1", "200", "5", "2"} <= set(tokens)


def test_preserves_comparison_and_arithmetic_operators() -> None:
    tokens = tokenize_scientific_english("p < 0.05; score ≥ 0.8; A/B; 10^5")

    assert "<" in tokens
    assert "≥" in tokens
    assert "/" in tokens
    assert "0.05" in tokens
    assert "0.8" in tokens
    assert "^" in tokens


def test_normalizes_unicode_dashes_and_composed_text() -> None:
    tokens = tokenize_scientific_english("Cafe\u0301 e5–small−v2")

    assert "café" in tokens
    assert "e5-small-v2" in tokens


def test_micro_sign_and_greek_mu_share_analyzed_form() -> None:
    assert tokenize_scientific_english("µg μg") == ("μg", "μg")


def test_punctuation_only_query_retains_supported_operators() -> None:
    assert tokenize_scientific_english("≤ ± ≈") == ("≤", "±", "≈")


def test_non_text_input_is_rejected() -> None:
    with pytest.raises(TypeError, match="text must be a string"):
        tokenize_scientific_english(None)  # type: ignore[arg-type]
