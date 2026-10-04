"""Unit tests for scientific sparse encoding of generation points (P35-12)."""

from __future__ import annotations

import asyncio
from collections.abc import Collection
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from research_platform.ingestion.generation_build import PassageInput
from research_platform.ingestion.generation_index import SparseLexicalSettings
from research_platform.ingestion.paper_index import PaperIndexInput
from research_platform.ingestion.sparse_build import (
    SparseEncoder,
    compute_lexical_averages,
    paper_lexical_text,
)
from research_platform.search.sparse_lexical import VocabularyRepository

SETTINGS = SparseLexicalSettings(
    "scientific-en", "v1", "scientific-en-v1", 1.5, 0.75, 4.0, 2.0
)


class _Inputs:
    async def load_passage_inputs(self, snapshot_id: UUID) -> tuple[PassageInput, ...]:
        return (
            PassageInput("e1", "alpha beta gamma delta", {}),
            PassageInput("e2", "...", {}),
            PassageInput("e3", "alpha beta", {}),
        )


class _Papers:
    async def snapshot_member_ids(self, snapshot_id: UUID) -> frozenset[str]:
        return frozenset({"W1", "W2"})

    async def load_known_papers(self) -> tuple[PaperIndexInput, ...]:
        return (
            PaperIndexInput(
                "W1", "Dense retrieval", "ignored abstract words", 2024, None, None
            ),
            PaperIndexInput("W2", "BM25", None, 2023, None, None),
            PaperIndexInput(
                "W3", "Not a member with many words", None, 2022, None, None
            ),
        )


class _Vocabulary:
    def __init__(self) -> None:
        self.terms: dict[str, int] = {}
        self.calls: list[set[str]] = []

    async def ensure_vocabulary(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def ensure_terms(
        self, vocabulary_id: str, terms: Collection[str]
    ) -> dict[str, int]:
        self.calls.append(set(terms))
        for term in sorted(set(terms)):
            self.terms.setdefault(term, len(self.terms))
        return {term: self.terms[term] for term in terms}


def test_averages_include_empty_rows_for_evidence() -> None:
    averages = asyncio.run(
        compute_lexical_averages(_Inputs(), cast(Any, _Papers()), uuid4())
    )
    # "..." analyzes to operator-free punctuation only, which yields no tokens.
    assert averages.evidence_document_count == 3
    assert averages.evidence_average_length == pytest.approx((4 + 0 + 2) / 3)


def test_paper_average_uses_member_titles_only() -> None:
    averages = asyncio.run(
        compute_lexical_averages(_Inputs(), cast(Any, _Papers()), uuid4())
    )
    assert averages.paper_document_count == 2
    assert averages.paper_average_length == pytest.approx((2 + 1) / 2)
    assert paper_lexical_text("  Title  ") == "Title"
    assert paper_lexical_text(None) == ""
    settings = averages.settings()
    assert (settings.analyzer, settings.vocabulary_id) == (
        "scientific-en",
        "scientific-en-v1",
    )


def test_encoder_extends_vocabulary_per_batch() -> None:
    vocabulary = _Vocabulary()
    encoder = SparseEncoder(cast(VocabularyRepository, vocabulary), SETTINGS)
    first = asyncio.run(encoder.encode_passages(["alpha beta", "beta"]))
    second = asyncio.run(encoder.encode_papers(["gamma"]))

    assert vocabulary.calls == [{"alpha", "beta"}, {"gamma"}]
    assert first[0][1] == ("alpha", "beta")
    assert first[0][0].indices == (0, 1)
    assert second[0][0].indices == (2,)
    # Same token count, different fixed averages: paper weights use the paper average.
    passage_weight = asyncio.run(encoder.encode_passages(["gamma"]))[0][0].values[0]
    assert second[0][0].values[0] != passage_weight


def test_encoder_rejects_other_analyzer() -> None:
    with pytest.raises(ValueError, match="different analyzer"):
        SparseEncoder(
            cast(VocabularyRepository, _Vocabulary()),
            SparseLexicalSettings("english", "v1", "v", 1.5, 0.75, 1.0, 1.0),
        )
