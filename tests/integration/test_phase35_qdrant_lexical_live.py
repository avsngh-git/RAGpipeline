"""Qdrant lexical branches reproduce BM25S rankings on live services (P35-13)."""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import httpx
import pytest

from research_platform.ingestion.generation_index import (
    GenerationIndexConfiguration,
    GenerationPoint,
    GenerationQdrantCollection,
    SparseLexicalSettings,
    paper_point_id,
    passage_point_id,
)
from research_platform.ingestion.sparse_build import SparseEncoder
from research_platform.persistence.migrations import apply_migrations
from research_platform.search.contracts import SearchFilters
from research_platform.search.lexical import (
    BM25_SCORING_SETTINGS,
    EvidenceLexicalDocument,
    LexicalRetriever,
    LexicalSearchResult,
    PaperLexicalDocument,
    build_evidence_index,
    build_paper_index,
)
from research_platform.search.lexical_analyzer import (
    ANALYZER_ID,
    ANALYZER_REVISION,
    tokenize_scientific_english,
)
from research_platform.search.lexical_branches import (
    QdrantEvidenceLexicalBranch,
    QdrantPaperLexicalBranch,
)
from research_platform.search.profile_manifest import load_frozen_profile
from research_platform.search.sparse_lexical import VocabularyRepository, average_length

TEST_DATABASE_URL = os.environ.get("RESEARCH_PLATFORM_TEST_DATABASE_URL")
TEST_QDRANT_URL = os.environ.get("RESEARCH_PLATFORM_TEST_QDRANT_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL or not TEST_QDRANT_URL,
        reason="requires the dedicated disposable PostgreSQL and Qdrant services",
    ),
]

ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_frozen_profile(ROOT / "benchmarks/phase2/frozen-profile-v10.toml")
PAPERS = ("W1001", "W1002", "W1003", "W1004", "W1005", "W1006")
YEARS = (2020, 2021, 2022, 2023, 2024, 2025)
TITLES = (
    "Cross-encoder reranking for retrieval-augmented generation",
    "BM25 remains a strong lexical baseline for scientific search",
    "Dense passage retrieval with contrastive pre-training",
    "Reciprocal rank fusion of BM25 and dense retrievers",
    "Evaluating nDCG@10 and Recall@20 on held-out scientific questions",
    "GPT-3.5 hallucination in retrieval-augmented question answering",
)
GENERATION_1 = (
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
    "Cross-encoder rerankers such as MiniLM-L6 are smaller than LLM rerankers.",
    "Retrieval-augmented generation reduces hallucination in open-domain QA.",
    "Contrastive pre-training of dense retrievers needs hard negatives.",
    "BM25 with k1=1.5 and b=0.75 is the Lucene default configuration.",
    "Query expansion with pseudo-relevance feedback helps BM25 on short queries.",
    "The reranker reorders the top 50 fused candidates before generation.",
    "Table 4: nDCG@10 of 0.652 for hybrid retrieval with reranking.",
    "Dense retrieval fails on rare scientific terms such as GPT-3.5 variants.",
    "Reciprocal rank fusion uses a rank constant of 60 for every retriever.",
    "Hallucination rates fall when cited passages are verified against claims.",
    "Recall@20 improves from 0.41 to 0.51 after adding lexical retrieval.",
    "Scientific tables keep headers, units and footnotes with each row group.",
    "Cross-encoder scoring of 2,048-token pairs runs in fp16 on the GPU.",
    "MRR@10 is reported with paired bootstrap confidence intervals.",
    "Sparse lexical vectors use an IDF modifier computed over the corpus.",
    "Lexical and dense retrieval agree on 49.9 of the top 50 candidates.",
    "Answer synthesis quotes each claim from a single cited passage.",
    "Retrieval-augmented generation with reranking answers 86% of questions.",
    "The held-out set contains 30 question families judged by source review.",
    "BM25 scores ties are broken by the stable evidence identifier.",
)
GENERATION_2 = (
    "BM25 reranking of retrieval-augmented generation added in a later generation.",
    "Cross-encoder nDCG@10 gains reported by a newly ingested paper.",
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
    "hallucination",
)


def _evidence_id(text: str, index: int) -> str:
    return "sha256:" + hashlib.sha256(f"{index}:{text}".encode()).hexdigest()


def _configuration(settings: SparseLexicalSettings) -> GenerationIndexConfiguration:
    suffix = uuid4().hex[:12]
    return GenerationIndexConfiguration(
        passages_collection=f"phase35-lexical-passages-{suffix}",
        papers_collection=f"phase35-lexical-papers-{suffix}",
        embedding_model="integration-fixture",
        embedding_revision="v1",
        preprocessing_revision="raw-text-v1",
        vector_size=2,
        distance="Cosine",
        batch_size=64,
        maximum_input_tokens=32,
        lexical=settings,
    )


def _settings(vocabulary_id: str) -> SparseLexicalSettings:
    return SparseLexicalSettings(
        analyzer=ANALYZER_ID,
        analyzer_revision=ANALYZER_REVISION,
        vocabulary_id=vocabulary_id,
        k1=BM25_SCORING_SETTINGS.k1,
        b=BM25_SCORING_SETTINGS.b,
        evidence_average_length=average_length(
            [tokenize_scientific_english(text) for text in GENERATION_1]
        ),
        paper_average_length=average_length(
            [tokenize_scientific_english(title) for title in TITLES]
        ),
    )


def _assert_same(expected: LexicalSearchResult, actual: LexicalSearchResult) -> None:
    assert [hit.stable_id for hit in actual.hits] == [
        hit.stable_id for hit in expected.hits
    ]
    assert [hit.paper_id for hit in actual.hits] == [
        hit.paper_id for hit in expected.hits
    ]
    for want, got in zip(expected.hits, actual.hits, strict=True):
        assert math.isclose(got.score, want.score, rel_tol=1e-4)
    assert (actual.available_count, actual.eligible_count, actual.truncated) == (
        expected.available_count,
        expected.eligible_count,
        expected.truncated,
    )
    assert actual.applied_filters == expected.applied_filters


def _with_services(
    operation: Callable[
        [VocabularyRepository, GenerationIndexConfiguration, httpx.AsyncClient],
        Awaitable[None],
    ],
) -> None:
    assert TEST_DATABASE_URL is not None and TEST_QDRANT_URL is not None
    assert urlparse(TEST_DATABASE_URL).path.removeprefix("/") == "research_test"

    async def exercise() -> None:
        await apply_migrations(TEST_DATABASE_URL)
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=3)
        configuration = _configuration(_settings(f"test-{uuid4().hex}"))
        async with httpx.AsyncClient(base_url=TEST_QDRANT_URL, timeout=30) as http:
            try:
                await operation(VocabularyRepository(pool), configuration, http)
            finally:
                for name in (
                    configuration.passages_collection,
                    configuration.papers_collection,
                ):
                    await http.delete(f"/collections/{name}")
                await pool.close()

    asyncio.run(exercise())


async def _encoder(
    vocabulary: VocabularyRepository, configuration: GenerationIndexConfiguration
) -> SparseEncoder:
    assert configuration.lexical is not None
    encoder = SparseEncoder(vocabulary, configuration.lexical)
    await encoder.prepare()
    return encoder


async def _collection(
    configuration: GenerationIndexConfiguration,
    role: str,
    http: httpx.AsyncClient,
    points: Sequence[GenerationPoint],
) -> GenerationQdrantCollection:
    collection = GenerationQdrantCollection(configuration, role, http)  # type: ignore[arg-type]
    await collection.ensure_collection()
    await collection.ensure_payload_indexes()
    await collection.upsert(points)
    return collection


def test_qdrant_scores_equal_bm25s_scores() -> None:
    texts = [(text, 1) for text in GENERATION_1] + [(t, 2) for t in GENERATION_2]
    documents = [
        EvidenceLexicalDocument(
            evidence_id=_evidence_id(text, index),
            paper_id=PAPERS[index % len(PAPERS)],
            document_id=uuid4(),
            extraction_id=uuid4(),
            source_artifact_sha256="0" * 64,
            text=text,
            publication_year=YEARS[index % len(YEARS)],
            evidence_kind="table" if text.startswith("Table") else "text",
            document_version_kind="published",
        )
        for index, (text, _generation) in enumerate(texts)
    ]
    bm25s = LexicalRetriever(
        build_evidence_index(
            tuple(documents[: len(GENERATION_1)]),
            PROFILE,
            snapshot_status="finalized",
        )
    )

    async def exercise(
        vocabulary: VocabularyRepository,
        configuration: GenerationIndexConfiguration,
        http: httpx.AsyncClient,
    ) -> None:
        encoder = await _encoder(vocabulary, configuration)
        encoded = await encoder.encode_passages([text for text, _ in texts])
        points = [
            GenerationPoint(
                point_id=passage_point_id(
                    document.evidence_id, configuration.configuration_id
                ),
                dense=(1.0, 0.5),
                sparse=sparse,
                payload={
                    "evidence_id": document.evidence_id,
                    "paper_id": document.paper_id,
                    "added_generation": generation,
                    "publication_year": document.publication_year,
                    "evidence_kind": document.evidence_kind,
                    "document_version_kind": document.document_version_kind,
                    "lexical_terms": list(terms),
                },
            )
            for document, (_, generation), (sparse, terms) in zip(
                documents, texts, encoded, strict=True
            )
        ]
        assert configuration.lexical is not None
        branch = QdrantEvidenceLexicalBranch(
            profile=PROFILE,
            passages=await _collection(configuration, "passages", http, points),
            vocabulary=vocabulary,
            settings=configuration.lexical,
            generation=1,
            candidate_limit=50,
        )
        for filters in (
            SearchFilters(),
            SearchFilters(year_from=2022, year_to=2024),
            SearchFilters(paper_ids=("W1001", "W1004"), evidence_kinds=("text",)),
        ):
            for query in QUERIES:
                for limit in (3, 20):
                    _assert_same(
                        bm25s.search_with_stats(query, limit=limit, filters=filters),
                        await branch.search_with_stats(
                            query, limit=limit, filters=filters
                        ),
                    )

    _with_services(exercise)


def test_qdrant_paper_scores_equal_bm25s_scores() -> None:
    bm25s = LexicalRetriever(
        build_paper_index(
            tuple(
                PaperLexicalDocument(paper_id, title, None)
                for paper_id, title in zip(PAPERS, TITLES, strict=True)
            ),
            PROFILE,
            snapshot_status="finalized",
        )
    )
    metadata_only = ("W1007", "BM25 reranking survey without ingested evidence")

    async def exercise(
        vocabulary: VocabularyRepository,
        configuration: GenerationIndexConfiguration,
        http: httpx.AsyncClient,
    ) -> None:
        encoder = await _encoder(vocabulary, configuration)
        rows = [*zip(PAPERS, TITLES, strict=True), metadata_only]
        encoded = await encoder.encode_papers([title for _, title in rows])
        points = [
            GenerationPoint(
                point_id=paper_point_id(paper_id, configuration.configuration_id),
                dense=(1.0, 0.5),
                sparse=sparse,
                payload={
                    "paper_id": paper_id,
                    "lexical_terms": list(terms),
                    **(
                        {}
                        if paper_id == metadata_only[0]
                        else {"indexed_generation": 1}
                    ),
                },
            )
            for (paper_id, _), (sparse, terms) in zip(rows, encoded, strict=True)
        ]
        assert configuration.lexical is not None
        branch = QdrantPaperLexicalBranch(
            profile=PROFILE,
            papers=await _collection(configuration, "papers", http, points),
            vocabulary=vocabulary,
            settings=configuration.lexical,
            generation=1,
            candidate_limit=50,
        )
        for eligible in (set(PAPERS), {"W1001", "W1002", "W1004"}):
            for query in QUERIES:
                _assert_same(
                    bm25s.search_with_stats(query, eligible_ids=eligible, limit=20),
                    await branch.search_with_stats(
                        query, eligible_ids=eligible, limit=20
                    ),
                )

    _with_services(exercise)
