---
status: accepted
date: 2026-09-28
---

# Accept the Phase 2 retrieval profile

> **Superseded in part (2026-09-30):** [ADR-0017](0017-phase2-accepted-profile-v10.md) replaces the E5-small-v2 embedding and MiniLM-L6-v2 reranker selection with `frozen-profile-v10` (gte-modernbert-base, Ettin-150M). The v11 result below is historical.

Phase 2 serves the finalized 100-paper snapshot with the frozen MiniLM-over-Hybrid-E5 profile: E5-small-v2 embeddings, BM25S 0.3.11 with `scientific-en-v1`, RRF rank constant 10, and MiniLM-L6-v2 reranking of a 16-item fused prefix with the configured whole-pool hybrid fallback. Paper results use strongest-passage aggregation with up to five distinct support passages; evidence results allow up to five items per paper. The unsupported-query cutoff remains disabled, so results make ranking claims only.

## Why this profile

Development comparisons selected the profile before held-out scoring. The fresh source-reviewed v11 assessment passed every frozen quality and operational gate without changing the profile or numeric limits. On that purposive ten-family sample, it achieved paper nDCG@10 0.9208, paper direct MRR@10 1.0000, evidence nDCG@10 0.6682, evidence direct MRR@10 0.6357 and source-anchor recall@10 0.5556. Warm p95 was 1,485.8 ms against the 1,500 ms ceiling. Hybrid E5 had slightly higher paper nDCG, while the selected reranked profile ranked evidence better and remained within the declared latency bound. The frozen settings and hashes are in [`frozen-profile-v9.toml`](../../benchmarks/phase2/frozen-profile-v9.toml) and [`acceptance-v9.toml`](../../benchmarks/phase2/acceptance-v9.toml); sanitized aggregates and limitations are in the [acceptance report](../reference/phase-2-acceptance-report.md).

## Consequences

The accepted profile is bound to the retained snapshot and its exact evidence selection. Changing the embedding model requires a new compatible index; changing ranking, selection, lexical analysis or model revisions requires a new profile identity. Any material profile change must be selected using development evidence and validated on a fresh source-reviewed held-out set. The v11 set is spent and cannot be used for tuning. The ten-family v11 result is directional, does not establish whole-literature quality, and includes no generated-answer evaluation. Public passage display remains disabled. The v11 pass was later superseded: R8 v12 failed 6 of 14 gates and Phase 2 remains open. [ADR-0014](0014-phase2-acceptance-method.md) (2026-09-29) replaces ten-family acceptance sets with a 30-family v13 set, unchanged gates and profile, and at most two acceptance runs. [ADR-0015](0015-phase2-acceptance-gate-revision.md) then revised the gates, and the R8 v14 assessment passed all 16 gates on 2026-09-30 with a different profile; see ADR-0017.
