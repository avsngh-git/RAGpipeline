# 9. Search

Search is the foundation of every answer, and it is the most heavily evaluated part of the system. It serves both direct API calls and the agent's tools.

## The served profile: `v10-qdrant`

A *retrieval profile* freezes every choice that affects ranking. The served one is [`frozen-profile-v10-qdrant.toml`](../../benchmarks/phase2/frozen-profile-v10-qdrant.toml), selected through [`active-profile.toml`](../../benchmarks/phase2/active-profile.toml).

| Stage | Setting |
| --- | --- |
| Lexical | BM25 with the `scientific-en-v1` analyzer, executed by Qdrant as sparse vectors with an IDF modifier (`qdrant-v1.19.1-lucene-idf`); top 50 |
| Dense | `Alibaba-NLP/gte-modernbert-base` at revision `e7f32e3c00f91d699e8c43b53106206bcc72bb22`, 768 dimensions, exact search; top 50 |
| Fusion | Reciprocal Rank Fusion (`rrf-v1`), rank constant 10; top 50 |
| Reranking | `cross-encoder/ettin-reranker-150m-v1` at revision `025501c4e0f9bbeb4c5b198318e0089ff061cc14`, fp16 profile precision; reranks the first 16 fused candidates, and the rest follow in fused order |
| Selection | Remove overlapping duplicates; up to 5 supporting passages per paper; evidence results within 4,000 tokens or 12,000 characters |
| Results | Up to 10 by default (maximum 50) |

### How it was chosen

The profile won a staged evaluation ([ADR-0017](../adr/0017-phase2-accepted-profile-v10.md)). Candidates were compared on development question families. The chosen profile was then frozen and scored once on a fresh held-out set of 30 families, where it passed all 16 gates. The [benchmarks](../reference/benchmarks.md) give the comparison with BM25-only, dense-only, unreranked hybrid and fixed-window chunking, and the [evaluation chapter](11-evaluation.md) explains the method.

Two honest caveats:

- Dense-only gte ranked **papers** better (nDCG@10 0.718 against 0.652). The hybrid-plus-reranker profile was chosen for **evidence** ranking (0.407 against 0.361), which is what answers cite.
- Three of the quality gates passed by margins inside sampling noise, after their thresholds had been lowered following a failed earlier assessment ([ADR-0015](../adr/0015-phase2-acceptance-gate-revision.md)).

### Why Qdrant runs the lexical search

Phase 2 accepted the profile using BM25S, an in-process Python BM25. Phase 3.5 moved lexical search into Qdrant as sparse vectors, so one service runs both branches and serves the evidence text ([ADR-0022](../adr/0022-phase35-qdrant-search-and-content.md)). The move inherited the Phase 2 acceptance only after a parity test: 84 of 84 lexical and 336 of 336 end-to-end development results were identical, with ordering differences only among float32-tied scores ([parity report](../reference/phase-3.5-lexical-parity-report.md)). BM25S remains available as a fallback with `RESEARCH_PLATFORM_LEXICAL_ENGINE=bm25s`.

## Modes

| Mode | Stages |
| --- | --- |
| `lexical` | Lexical only |
| `dense` | Dense only |
| `hybrid` | Lexical + dense + RRF |
| `reranked` | Hybrid + cross-encoder (the default for the agent) |

Failures are explicit. If reranking cannot run, for example because a pair exceeds its token budget or inference fails, the response reports `effective_mode: "hybrid"` with a warning and returns the complete fused order. Evaluation counts these fallbacks separately (the held-out run had none).

## Filters

Filters decide eligibility **before** ranking, so lexical and dense top-k are drawn only from eligible records. A record with missing metadata never silently satisfies a filter.

| Filter | Applies to |
| --- | --- |
| `year_from`, `year_to` | Papers and evidence (inclusive) |
| `paper_ids` | Restrict to up to 100 papers |
| `evidence_kinds` | Evidence search: `text`, `table`, `table_row_group`, `caption`, `figure`, `equation` |
| `document_version_kinds` | `published`, `preprint`, `other`, `unknown` |

Every search also requires the served `snapshot_id` and `retrieval_profile_id` (from `GET /v1/serving`), so results are always tied to a known corpus and configuration.

## Paper search versus evidence search

- **Paper search** returns one hit per paper. Title and abstract matching and passage matching both contribute; the paper's evidence score starts from its strongest passage, and up to five supporting passages are attached.
- **Evidence search** returns individual evidence units. Tables come back with labelled cells (every value next to its row and column headers), plus caption, units and footnotes.

## What a score means

Scores order results within one response. They are **not** probabilities of relevance, and no relevance cutoff is applied, because none has been calibrated for this profile. Every response says `ranking_interpretation: "ranking_only"`. A response with `result_status: "ranked_candidates"` means "here is a ranking", not "the question is answerable". Answerability is decided later, by quote verification during a research run.

## Performance

On the RTX 3050 the held-out run measured a warm median of 790 ms and a p95 of 1,016 ms per request. Cold model loading took 6.5 s, and the models allocated 634 MB of GPU memory. CPU latency in the demo has not been benchmarked; reranking 16 long pairs on CPU took minutes in an earlier measurement, which is why live research runs keep retrieval on the GPU.

## Related papers and citations

- `get_references` and `get_citations` page through stored one-hop citation edges in PostgreSQL.
- `find_related_papers` ranks papers connected through shared references and co-citations.

Multi-hop traversal happens in the agent, bounded by `max_citation_depth` (default 2). Citation data is real OpenAlex data; there is no simulated graph.

Next: [Research runs](10-research-runs.md).
