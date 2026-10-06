"""Scientific BM25 sparse vectors whose Qdrant scores equal BM25S Lucene scores.

BM25S (Lucene variant) scores a document as the sum, over query tokens, of
``idf(t) * tf / (k1 * ((1 - b) + b * dl / avgdl) + tf)``, with
``idf = ln(1 + (N - df + 0.5) / (df + 0.5))``. Document vectors here hold the
term-frequency part; Qdrant's ``idf`` modifier supplies the IDF at query time
(P35-02). Query weights are token counts, because BM25S adds a repeated query token's
column once per occurrence and drops tokens outside the vocabulary.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence

import asyncpg  # type: ignore[import-untyped]

from research_platform.ingestion.generation_index import SparseVector

SCIENTIFIC_VOCABULARY_ID = "scientific-en-v1"


def document_term_weights(
    tokens: Sequence[str], *, k1: float, b: float, average_length: float
) -> dict[str, float]:
    """BM25S Lucene term-frequency component for each distinct token."""
    if average_length <= 0:
        raise ValueError("average_length must be positive")
    norm = k1 * ((1 - b) + b * len(tokens) / average_length)
    return {token: tf / (norm + tf) for token, tf in Counter(tokens).items()}


def query_term_weights(tokens: Sequence[str]) -> dict[str, float]:
    """Occurrence count per token, as BM25S sums repeated query tokens."""
    return {token: float(count) for token, count in Counter(tokens).items()}


def average_length(token_lists: Iterable[Sequence[str]]) -> float:
    """Mean token count, counting empty documents as BM25S does."""
    lengths = [len(tokens) for tokens in token_lists]
    if not lengths:
        raise ValueError("average length needs at least one document")
    return sum(lengths) / len(lengths)


def lucene_idf(document_frequency: int, document_count: int) -> float:
    """Lucene IDF, the formula Qdrant's ``idf`` modifier applies."""
    return math.log(
        1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
    )


def to_sparse_vector(
    weights: Mapping[str, float], term_ids: Mapping[str, int]
) -> SparseVector:
    """Sorted sparse vector over terms with IDs; terms without an ID are dropped."""
    items = sorted(
        (term_ids[term], weight) for term, weight in weights.items() if term in term_ids
    )
    return SparseVector(
        indices=tuple(index for index, _ in items),
        values=tuple(weight for _, weight in items),
    )


def lexical_terms(tokens: Sequence[str]) -> tuple[str, ...]:
    """Sorted distinct tokens, stored in the payload for exact positive-match counts."""
    return tuple(sorted(set(tokens)))


class VocabularyRepository:
    """Append-only token-to-ID mapping per vocabulary."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_vocabulary(
        self, vocabulary_id: str, *, analyzer: str, analyzer_revision: str
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO lexical_vocabularies
                    (vocabulary_id, analyzer, analyzer_revision)
                VALUES ($1, $2, $3)
                ON CONFLICT (vocabulary_id) DO NOTHING
                """,
                vocabulary_id,
                analyzer,
                analyzer_revision,
            )
            row = await connection.fetchrow(
                "SELECT analyzer, analyzer_revision FROM lexical_vocabularies "
                "WHERE vocabulary_id = $1",
                vocabulary_id,
            )
        if row is None or (row["analyzer"], row["analyzer_revision"]) != (
            analyzer,
            analyzer_revision,
        ):
            raise ValueError("vocabulary exists with a different analyzer")

    async def ensure_terms(
        self, vocabulary_id: str, terms: Collection[str]
    ) -> dict[str, int]:
        """Return IDs for every term, assigning new consecutive IDs in sorted order."""
        wanted = sorted(set(terms))
        if not wanted:
            return {}
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    f"vocabulary:{vocabulary_id}",
                )
                known = await self._lookup(connection, vocabulary_id, wanted)
                missing = [term for term in wanted if term not in known]
                if missing:
                    start = await connection.fetchval(
                        "SELECT COALESCE(max(term_id) + 1, 0) FROM lexical_terms "
                        "WHERE vocabulary_id = $1",
                        vocabulary_id,
                    )
                    await connection.executemany(
                        "INSERT INTO lexical_terms (vocabulary_id, term, term_id) "
                        "VALUES ($1, $2, $3)",
                        [
                            (vocabulary_id, term, int(start) + offset)
                            for offset, term in enumerate(missing)
                        ],
                    )
                    known.update(
                        {
                            term: int(start) + offset
                            for offset, term in enumerate(missing)
                        }
                    )
        return known

    async def lookup(
        self, vocabulary_id: str, terms: Collection[str]
    ) -> dict[str, int]:
        """IDs of known terms only; never inserts."""
        wanted = sorted(set(terms))
        if not wanted:
            return {}
        async with self._pool.acquire() as connection:
            return await self._lookup(connection, vocabulary_id, wanted)

    @staticmethod
    async def _lookup(
        connection: asyncpg.Connection, vocabulary_id: str, terms: list[str]
    ) -> dict[str, int]:
        rows = await connection.fetch(
            "SELECT term, term_id FROM lexical_terms "
            "WHERE vocabulary_id = $1 AND term = ANY($2::text[])",
            vocabulary_id,
            terms,
        )
        return {str(row["term"]): int(row["term_id"]) for row in rows}
