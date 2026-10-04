"""Scientific sparse BM25 weights reproduce BM25S Lucene scores (P35-11)."""

from __future__ import annotations

import math
from collections import Counter

import bm25s
import numpy as np
import pytest

from research_platform.search.lexical import BM25_SCORING_SETTINGS
from research_platform.search.lexical_analyzer import tokenize_scientific_english
from research_platform.search.sparse_lexical import (
    average_length,
    document_term_weights,
    lexical_terms,
    lucene_idf,
    query_term_weights,
    to_sparse_vector,
)

K1 = BM25_SCORING_SETTINGS.k1
B = BM25_SCORING_SETTINGS.b

CORPUS = (
    "Reranking with a cross-encoder improves nDCG@10 by 0.5% over BM25.",
    "GPT-3.5 and GPT-4 were evaluated with retrieval-augmented generation.",
    "Dense retrieval recall@100 exceeds 90% on Natural Questions.",
    "",
    "Table 2: accuracy ±0.3 for k=60 reciprocal rank fusion.",
    "BM25 BM25 BM25 remains a strong lexical baseline.",
    "Hybrid search fuses BM25 and dense scores with RRF.",
    "The ColBERT-v2 late-interaction model uses 128-dim vectors.",
    "Latency p95 ≤ 2,000 ms for the reranked profile.",
    "We report nDCG@10, MRR@10 and Recall@20 on the held-out set.",
    "Cross-encoder rerankers such as MiniLM-L6 are smaller.",
    "Retrieval-augmented generation reduces hallucination in QA.",
)
QUERIES = (
    "BM25 reranking",
    "nDCG@10 improvement",
    "GPT-3.5 retrieval-augmented generation",
    "k=60 fusion",
    "dense retrieval recall",
    "cross-encoder MiniLM-L6",
    "BM25 BM25 baseline",
    "p95 latency ≤ 2,000 ms",
    "unknownterm only",
    "held-out Recall@20",
)


def _bm25s_engine(tokenized: list[list[str]]):
    scoring = BM25_SCORING_SETTINGS
    engine = bm25s.BM25(
        k1=scoring.k1,
        b=scoring.b,
        delta=scoring.delta,
        method=scoring.method,
        idf_method=scoring.idf_method,
        dtype=scoring.dtype,
        int_dtype=scoring.int_dtype,
        backend=scoring.backend,
        csc_backend=scoring.csc_backend,
        auto_compile=scoring.auto_compile,
    )
    engine.index(tokenized, create_empty_token=True, show_progress=False)
    return engine


def test_document_weights_match_bm25s_formula() -> None:
    weights = document_term_weights(["a", "a", "b"], k1=1.5, b=0.75, average_length=2.0)
    norm = 1.5 * (0.25 + 0.75 * 3 / 2.0)
    assert weights == pytest.approx({"a": 2 / (norm + 2), "b": 1 / (norm + 1)})
    with pytest.raises(ValueError):
        document_term_weights(["a"], k1=1.5, b=0.75, average_length=0)


def test_query_weights_count_repeated_tokens() -> None:
    assert query_term_weights(["bm25", "bm25", "x"]) == {"bm25": 2.0, "x": 1.0}


def test_unknown_terms_are_dropped_and_indices_sorted() -> None:
    vector = to_sparse_vector({"b": 0.2, "a": 0.1, "zz": 0.9}, {"a": 7, "b": 3})
    assert vector.indices == (3, 7)
    assert vector.values == (0.2, 0.1)
    assert to_sparse_vector({}, {}).indices == ()


def test_empty_document_gives_empty_vector_and_counts_in_average() -> None:
    assert (
        to_sparse_vector(
            document_term_weights([], k1=K1, b=B, average_length=2.0), {"a": 1}
        ).indices
        == ()
    )
    assert average_length([["a", "b"], [], ["c"]]) == 1.0
    assert lexical_terms(["b", "a", "b"]) == ("a", "b")


def test_scores_equal_bm25s_on_scientific_corpus() -> None:
    tokenized = [list(tokenize_scientific_english(text)) for text in CORPUS]
    engine = _bm25s_engine(tokenized)
    average = average_length(tokenized)
    n = len(tokenized)
    df = Counter(token for tokens in tokenized for token in set(tokens))
    vocabulary = {term: index for index, term in enumerate(sorted(df))}
    documents = [
        to_sparse_vector(
            document_term_weights(tokens, k1=K1, b=B, average_length=average),
            vocabulary,
        )
        for tokens in tokenized
    ]
    terms_by_id = {index: term for term, index in vocabulary.items()}
    for query in QUERIES:
        tokens = list(tokenize_scientific_english(query))
        expected = np.asarray(engine.get_scores(tokens)) if tokens else np.zeros(n)
        query_vector = to_sparse_vector(query_term_weights(tokens), vocabulary)
        query_weights = dict(
            zip(query_vector.indices, query_vector.values, strict=True)
        )
        for row, document in enumerate(documents):
            score = sum(
                lucene_idf(df[terms_by_id[index]], n) * value * query_weights[index]
                for index, value in zip(document.indices, document.values, strict=True)
                if index in query_weights
            )
            assert math.isclose(score, float(expected[row]), rel_tol=1e-5, abs_tol=1e-6)
