---
status: accepted
date: 2026-09-30
---

# Accept Phase 2 with frozen profile v10 (gte-modernbert-base + BM25S + Ettin-150M)

Accepted by the project owner on 2026-09-30, who approved the model choices below.
All judgments are assistant-reviewed; none are human-verified. This ADR replaces the
E5-small-v2 embedding and MiniLM-L6-v2 reranker selection in
[ADR-0012](0012-phase2-accepted-retrieval-profile.md). ADR-0012's BM25S lexical choice,
strongest-passage paper aggregation, per-paper limits, disabled unsupported-query cutoff
and snapshot binding carry over unchanged.

## Context

- **v11 pass superseded.** ADR-0012 accepted the MiniLM-over-Hybrid-E5 profile on the
  ten-family v11 set. Later sets did not converge: v12 failed 6 of 14 gates and the
  30-family v13 set, run under [ADR-0014](0014-phase2-acceptance-method.md), failed 10 of 14.
- **Development diagnosis.** The
  [post-v13 diagnosis](../research/phase-2-development-diagnosis-post-v13.md) re-judged the
  21 development families with the v13 method. It found that the small models limit ranking:
  the E5-small embedder misses answer passages, and the 512-token MiniLM reranker hits its
  pair budget and falls back on about 23% of requests. Ten development-only paper-ordering
  variants on the existing models did not reach the old 0.80 paper gate.
- **Gate revision.** [ADR-0015](0015-phase2-acceptance-gate-revision.md) lowered three
  quality gates and added relative-to-BM25 gates for one fresh set.
  [ADR-0016](0016-phase2-warm-latency-5000ms.md) raised warm p95 to 5,000 ms so heavier
  models fit the 4 GB RTX 3050.
- **Candidates.** No separate model-candidates note exists (`docs/research/phase-2-model-candidates-2026.md`
  was not written). The choice rests on ADR-0015, the diagnosis, the
  [development report](../research/phase-2-development-report.md) and the earlier
  [reranker candidate research](../research/phase-2-reranker-candidate-research.md). The
  development report records the gte-hybrid + Ettin configuration at paper nDCG@10 0.729
  and evidence nDCG@10 0.489 on the re-judged 21 development families, both above the new
  gates (0.65, 0.40). A dense-only gte profile scored 0.757 paper nDCG there. The private
  development harness was lost when `/tmp` was cleared, so this is a retained aggregate, not
  a re-runnable comparison.

## Decision

Serve the finalized 100-paper snapshot with
[`frozen-profile-v10`](../../benchmarks/phase2/frozen-profile-v10.toml)
(`sha256:52a152db9fb350c91810353650864eaffef0b3fe148fde9781956373d3fe5449`):

- **Dense:** gte-modernbert-base replaces E5-small-v2.
- **Lexical:** BM25S 0.3.11 with `scientific-en-v1`, unchanged.
- **Fusion:** hybrid reciprocal rank fusion, rank constant 10, unchanged. The hybrid pipeline
  is kept as locked in section 9.1 of the source of truth; the owner chose not to replace it
  with dense-only retrieval.
- **Reranker:** Ettin-150M replaces MiniLM-L6-v2: fp16, 2,048-token query-passage pairs,
  top-k 16 of the fused prefix, with the existing whole-pool hybrid fallback.
- **Unchanged:** selection rules, paper/evidence result limits, disabled cutoff, permissions.

Acceptance evidence is the one-time R8 v14 assessment (30 families, freeze commit `82694aa`,
hosted CI run 36740163129), which passed all 16 acceptance-v14 gates on 2026-09-30. Gate
values, intervals, baselines and caveats are in the
[acceptance report](../reference/phase-2-acceptance-report.md).

## Why this profile

- The diagnosis located the limits in the embedder and reranker, not in fusion or selection.
- The v14 run met every gate with no hard failures and no reranker fallbacks; warm p95 was
  1,016 ms against 5,000 ms, cold load 6.5 s and CUDA allocation 0.63 GB against 1 GiB.
- The selected profile beat BM25 on paper and evidence nDCG@10 with 95% lower bounds of
  0.169 and 0.096, and ranked evidence better than dense gte and hybrid gte.

## Consequences

- The accepted profile is bound to the retained snapshot and its exact evidence selection.
  Changing the embedding model requires a new compatible index; changing ranking, selection,
  lexical analysis or model revisions requires a new profile identity, development evidence
  and a fresh source-reviewed held-out set. The v14 set is spent and cannot be used for tuning.
- Three quality gates passed by 0.002, 0.007 and 0.012, inside sampling noise, after gates
  were lowered post v13. v13 stays failed under its own gates. The pass is directional and
  covers ranking on one snapshot only, with assistant-reviewed labels.
- Dense gte alone ranked papers better than the selected profile (paper nDCG@10 0.7183 against
  0.6522; selected minus dense −0.0661, 95% interval [−0.1205, −0.0148]). Improving paper
  ordering is a known target and needs its own development evidence.
- Larger models raise cold load (6.5 s) and GPU memory (0.63 GB) against the 4 GB laptop
  budget; CPU operation and GPU-free CI are unchanged.
- Public passage display stays disabled; no generated-answer evaluation is included.
- Phase 3 is separate, has not started, and begins only on an owner decision.

## Alternatives considered

- **Keep E5-small-v2 and MiniLM.** Rejected: development diagnosis shows these models limit
  ranking, and they failed v12 and v13 on the original gates.
- **Dense-only gte.** Ranked papers better on v14, but the owner kept the locked hybrid
  pipeline, and the selected profile ranks evidence better.
- **Another paper-ordering or fusion-constant change.** Rejected: ten development variants
  did not clear the old gates and the k=3 versus k=10 difference was uncertain.
