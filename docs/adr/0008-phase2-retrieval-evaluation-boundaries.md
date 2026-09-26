---
status: accepted
date: 2026-09-26
---

# Freeze source evidence while comparing retrieval configurations

Phase 2 needs fair retrieval comparisons and a usable private local API without
rewriting the Phase 1 corpus. We will retain the accepted 100-paper snapshot and
create separately identified experimental snapshots/indexes that share unchanged
source artifacts and extraction. Benchmark relevance refers to source passages
and table cells rather than one chunking scheme. Normal research uses finalized
variants; explicitly scoped evaluation may inspect experimental drafts.

The user approved these boundaries and delegated implementation, calibration and
source review. New judgments are assistant-reviewed and disclose uncertainty;
Phase 1 human-confirmed samples do not confer human verification on new labels.
Calibration/development data selects models and thresholds, followed by a frozen
held-out evaluation. A measured simpler method may become the default.

## Alternatives and consequences

Mutating the accepted index in place would simplify experimentation but erase
provenance and mix model/chunk meanings. Chunk-ID-only judgments would be easier
but favor the chunker used during annotation. Versioned variants and canonical
source anchors cost storage/mapping work, while allowing meaningful comparisons
and protecting previously accepted evidence. Cleanup must respect retained variants.

Private local evidence inspection is distinct from public passage display. Existing
storage/index permissions are required; public-display flags stay unchanged. Trusted
execution configuration controls local inspection at service boundaries, not a
request parameter. Public exposure requires a separate policy/permission decision.

Phase 2 includes BM25 lexical, dense, RRF hybrid and cross-encoder comparisons,
filters, paper/evidence APIs and bounded stored one-hop graph lookups. BM25S and
the approved model shortlist are pilot candidates, not unmeasured permanent
selections. Graph-based ranking, new corpus acquisition, generation, MCP and public
deployment remain outside this phase. External scientific benchmarks are optional
follow-up work, and reported conclusions are limited accordingly.

The [source of truth](../agents/scientific-research-platform-source-of-truth.md#94-phase-2-retrieval-and-evaluation-policy--locked)
owns the approved policy. The [roadmap](../plans/phase-2-retrieval-evaluation.md)
and [evaluation protocol](../plans/phase-2-evaluation-protocol.md) define execution.
Exact persistence/schema changes require a separate implementation ADR when needed.
