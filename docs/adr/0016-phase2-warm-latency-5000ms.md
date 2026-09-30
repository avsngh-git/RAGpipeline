---
status: accepted
date: 2026-09-29
---

# Raise the Phase 2 warm-latency acceptance limit to 5,000 ms

Approved by the project owner on 2026-09-29. This ADR supersedes the 2,000 ms limit in
[ADR-0013](0013-phase2-warm-latency-acceptance.md) for future acceptance runs only.

## Context
The [development diagnosis](../research/phase-2-development-diagnosis-post-v13.md) shows that the small models limit
ranking quality. The E5-small embedder misses answer passages, and the 512-token MiniLM reranker falls back on about
23% of requests. The selected profile's warm p95 is about 0.9 s, so the 2,000 ms limit leaves little room to evaluate
stronger embedding or reranking models on the 4 GB RTX 3050.

## Decision
Future Phase 2 acceptance runs use a maximum warm p95 of 5,000 ms, for single-user interactive search on the reference
laptop. The separate 30-second per-request deadline, the other 13 gates and all earlier assessment outcomes (v3–v13,
each judged under its own frozen limit) are unchanged. The new limit takes effect in the next versioned acceptance
config (acceptance-v14 or later), which is frozen before any new held-out scoring.

## Consequences
- Heavier rerankers and embedders become eligible for development comparison. Any model change still needs
  development validation and a fresh held-out run.
- Searches may feel slower. Warm p95 up to 5 s is accepted for a private research tool; cold-start costs are still
  reported separately.
- Alternative: keep 2,000 ms. Rejected because it would rule out most of the stronger candidate models on this hardware.
