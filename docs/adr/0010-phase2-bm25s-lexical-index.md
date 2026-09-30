---
status: accepted
date: 2026-09-26
---

# Use BM25S for Phase 2 lexical indexes

Use the verified `bm25s==0.3.11` wheel (`sha256:3d1d28badb299d6fc9324111e5c8276927e990b908607b39ff9bd65b102e9a24`) with `scientific-en-v1`, explicit Lucene scoring (`k1=1.5`, `b=0.75`, float32) and NumPy retrieval/CSC backends for private local evidence and paper indexes. The accepted-corpus pilot showed practical build and query cost at 44,277 chunks, and the adapter resolves the measured `weight_mask` issue by selecting top-k only among authoritative eligible row IDs; these results establish feasibility, not relevance quality ([pilot report](../research/phase-2-bm25s-pilot-research.md)). The Phase 2 evaluation accepted BM25S 0.3.11 with this analyzer for the lexical profile. Later library or analyzer changes require a new development comparison and fresh held-out validation; the accepted retrieval profile is recorded in [ADR-0012](0012-phase2-accepted-retrieval-profile.md).
