"""Scientific BM25 sparse vectors for generation points (P35-12, ADR-0022 item 3).

Average lengths are fixed per index configuration from generation 1. Evidence counts
every selected chunk, including chunks with no tokens; papers count only snapshot
members and use the title alone, matching the Phase 2 BM25S paper index (see the
P35-07 finding in the Phase 3.5 handoff).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from research_platform.ingestion.generation_build import PassageInputSource
from research_platform.ingestion.generation_index import (
    SparseLexicalSettings,
    SparseVector,
)
from research_platform.ingestion.paper_index import (
    PaperIndexRepository,
    paper_lexical_text,
)
from research_platform.search.lexical import BM25_SCORING_SETTINGS
from research_platform.search.lexical_analyzer import (
    ANALYZER_ID,
    ANALYZER_REVISION,
    tokenize_scientific_english,
)
from research_platform.search.sparse_lexical import (
    SCIENTIFIC_VOCABULARY_ID,
    VocabularyRepository,
    average_length,
    document_term_weights,
    lexical_terms,
    to_sparse_vector,
)


@dataclass(frozen=True)
class LexicalAverages:
    evidence_average_length: float
    paper_average_length: float
    evidence_document_count: int
    paper_document_count: int

    def settings(self) -> SparseLexicalSettings:
        return SparseLexicalSettings(
            analyzer=ANALYZER_ID,
            analyzer_revision=ANALYZER_REVISION,
            vocabulary_id=SCIENTIFIC_VOCABULARY_ID,
            k1=BM25_SCORING_SETTINGS.k1,
            b=BM25_SCORING_SETTINGS.b,
            evidence_average_length=self.evidence_average_length,
            paper_average_length=self.paper_average_length,
        )


async def compute_lexical_averages(
    inputs: PassageInputSource, papers: PaperIndexRepository, snapshot_id: UUID
) -> LexicalAverages:
    passages = await inputs.load_passage_inputs(snapshot_id)
    members = await papers.snapshot_member_ids(snapshot_id)
    member_papers = [
        paper for paper in await papers.load_known_papers() if paper.paper_id in members
    ]
    if len(member_papers) != len(members):
        raise ValueError("every snapshot member must be a known paper")
    evidence_tokens = [tokenize_scientific_english(item.text) for item in passages]
    paper_tokens = [
        tokenize_scientific_english(paper_lexical_text(paper.title))
        for paper in member_papers
    ]
    return LexicalAverages(
        evidence_average_length=average_length(evidence_tokens),
        paper_average_length=average_length(paper_tokens),
        evidence_document_count=len(evidence_tokens),
        paper_document_count=len(paper_tokens),
    )


class SparseEncoder:
    """Encode passages and papers with fixed averages, extending the vocabulary."""

    def __init__(
        self, vocabulary: VocabularyRepository, settings: SparseLexicalSettings
    ) -> None:
        if (settings.analyzer, settings.analyzer_revision) != (
            ANALYZER_ID,
            ANALYZER_REVISION,
        ):
            raise ValueError("sparse settings name a different analyzer")
        self._vocabulary = vocabulary
        self._settings = settings

    async def prepare(self) -> None:
        await self._vocabulary.ensure_vocabulary(
            self._settings.vocabulary_id,
            analyzer=self._settings.analyzer,
            analyzer_revision=self._settings.analyzer_revision,
        )

    async def encode_passages(
        self, texts: Sequence[str]
    ) -> tuple[tuple[SparseVector, tuple[str, ...]], ...]:
        return await self._encode(texts, self._settings.evidence_average_length)

    async def encode_papers(
        self, texts: Sequence[str]
    ) -> tuple[tuple[SparseVector, tuple[str, ...]], ...]:
        return await self._encode(texts, self._settings.paper_average_length)

    async def _encode(
        self, texts: Sequence[str], average: float
    ) -> tuple[tuple[SparseVector, tuple[str, ...]], ...]:
        tokenized = [tokenize_scientific_english(text) for text in texts]
        term_ids = await self._vocabulary.ensure_terms(
            self._settings.vocabulary_id,
            {token for tokens in tokenized for token in tokens},
        )
        return tuple(
            (
                to_sparse_vector(
                    document_term_weights(
                        tokens,
                        k1=self._settings.k1,
                        b=self._settings.b,
                        average_length=average,
                    ),
                    term_ids,
                ),
                lexical_terms(tokens),
            )
            for tokens in tokenized
        )
