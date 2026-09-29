# Phase 2 — Agent handoff

Updated: 2026-09-29. The earlier v3 assessment failed four frozen gates and v11
passed historically. The one-time R8 v12 assessment has now completed and failed six
of 14 gates; the selected profile passed warm p95 at 894.3 ms against the 2,000 ms
gate. Phase 2 remains open, and v12 is spent and sealed from tuning. The owner
approved [ADR-0014](../adr/0014-phase2-acceptance-method.md) on 2026-09-29: v13 is
enlarged to 30 held-out families with unchanged gates. Follow the
[completion plan](phase-2-improvement-plan.md), the authoritative
[source of truth](../agents/scientific-research-platform-source-of-truth.md), the
[roadmap](phase-2-retrieval-evaluation.md), and the
[evaluation protocol](phase-2-evaluation-protocol.md). Detailed prior checkpoints are
in the [handoff history archive](phase-2-agent-handoff-history.md).

## Current progress

- R1–R5 are implemented and their focused checks passed. Exact selection is reused
  only within an active repository lease; embedding inference is bounded across
  cancellation; evaluation records distinguish fallback from warnings; acceptance
  tables are generated from checked gate records.
- R6 development diagnostics used only synthetic inputs and allowlisted q11–q19. Three
  100-request sessions had p95 851–894 ms, no hard failures, and 23% typed pair-overflow
  fallback, below the frozen 35% allowance. No pair-format or profile change is
  justified. Sanitized results are in the
  [development report](../research/phase-2-development-report.md); raw output remains
  private under `/tmp`.
- R7 local work is complete: the digest-checked active-profile pointer resolves v9 in
  runtime, CLI, tests and the packaged image. Offline startup/readiness and both live
  API routes passed with local caches. Measured asset sizes and cache-retention guidance
  are in the [development report](../research/phase-2-development-report.md). Checks:
  451 offline tests, 21 fresh PostgreSQL/Qdrant integrations, Ruff lint/format, mypy,
  `pip check`, `pip-audit`, and Linux AMD64 Docker build/image smoke pass on frozen
  code revision `586f83c`. Hosted CI passed on that exact revision in run
  [36445793795](https://github.com/avsngh-git/RAGpipeline/actions/runs/36445793795). The
  active-profile pointer, frozen-profile v9, and acceptance-v9 SHA-256 values are
  recorded in the development report.
- R8 source preparation has a sanitized screen of 12 accepted-snapshot anchors in the
  [source-screening report](../research/phase-2-r8-source-screening.md). It creates no
  questions or labels and cannot certify full freshness against unavailable spent-family
  identities. Two bounded missing-evidence source reviews are complete: the access-control
  review checked six supplied candidate papers and found no persistent user/role/tenant
  retrieval-leakage test ([review note](../research/phase-2-r8-access-control-source-review.md));
  the index-update review checked 10 supplied candidate papers and found no direct
  source-change or deletion experiment ([review note](../research/phase-2-r8-index-update-source-review.md)).
  The end-user evidence scan covers all 100 accepted snapshot members and records 72
  source-context hits across 40 papers; primary-source checks of the closest candidates
  found no study meeting the fixed end-user task comparison criterion ([review note](../research/phase-2-r8-end-user-study-source-review.md)).
  All three absence findings are bounded by their stated scan/candidate scopes and do
  not claim a literature-wide absence. R8 v12 was prepared, frozen and assessed once;
  six quality/source gates failed while the latency gate passed. The sanitized result is
  in the [acceptance report](../reference/phase-2-acceptance-report.md). Keep this spent
  set private and sealed from further tuning.
- The 2026-09-29 calibration plus q11–q19 RRF follow-up compared paper constants
  1, 3, 5 and 10. The best reviewed-development mean was k=3 (0.7008 nDCG@10), but
  its paired 95% family-bootstrap interval versus k=10 crossed zero; keep frozen k=10.
  All four 19-request p95 samples were below the prospective 2,000 ms limit and are
  diagnostic only. A cold-start warmup regression was fixed and covered by a focused
  test; the 10-second live query watchdog is unchanged. Details are in the
  [development report](../research/phase-2-development-report.md). This work does not
  reopen or reveal v12. The startup fix and focused regression test passed hosted CI
  on code-and-test commit `68218f1` ([run 36511846347](https://github.com/avsngh-git/RAGpipeline/actions/runs/36511846347)).
- V13 development review added one supported comparison family and one unsupported
  family to actual-profile diagnostics. The selected reranked profile retrieved all
  required source anchors on the single positive family; the unsupported family had
  contextual near-miss material but no direct source-positive passage. This sample
  does not establish acceptance or justify changing frozen v9 / RRF k=10. The sanitized
  summary is in the [development report](../research/phase-2-development-report.md).
- V13 acceptance preparation verified inclusive publication-year filter counts against
  the accepted 100-paper snapshot: 29 papers fall in 2020–2021, including seven screened
  source documents. The [source map](../research/phase-2-v13-heldout-source-evidence-map.md)
  records the supporting metadata counts. A read-only 38-variant literal screen covered
  all 100 titles and all 44,277 selected chunks; all 100 snapshot papers have searchable
  chunks, while abstract-index metadata is available for 10. This is storage coverage,
  not semantic proof of absence: matched sources still need direct adjudication and
  literal no-hits are not conclusive. The v13 development-only unsupported example had
  contextual near matches but no direct source-positive passage; it does not count toward
  held-out floors. A separate v13 gate config and acceptance runner preserve the v10
  thresholds and v12 scoring/timing procedure; v12 code and freeze remain unchanged.
  Hosted CI passed for commit `557277a` (run
  [36554779665](https://github.com/avsngh-git/RAGpipeline/actions/runs/36554779665)). The
  source adjudication, source-reviewed family records (now 30 held-out under ADR-0014),
  final freeze, and one-time v13 acceptance run remain open; no held-out scores have been produced.

## Current continuation handoff — assistant-reviewed 2026-09-29

### Verified current state

- Worktree: `/tmp/ragpipeline-phase2-ci-safe`, branch `codex/phase2-ci-safe`, clean at
  commit `1612975` (`docs: record v13 source scan coverage`). Hosted CI passed for this
  commit in [run 36557977127](https://github.com/avsngh-git/RAGpipeline/actions/runs/36557977127).
  Publication to the existing draft PR branch is authorized; do not merge.
- R8 v12 remains the latest held-out acceptance result: 8/14 gates passed. Warm p95
  was 894.349 ms against 2,000 ms and passed. Six paper/evidence/source-quality gates
  failed; see the [acceptance report](../reference/phase-2-acceptance-report.md).
  The v10 value of 1,602.2 ms is historical and was measured against its earlier
  1,500 ms gate.
- The two authorized v13 additions are development-only. The positive comparison's
  sources and retrieval stages were checked; the selected profile returned its
  required anchors. The unsupported example returned contextual near matches. Do not
  count either family toward held-out floors or use them as acceptance results.
- The v13 read-only corpus audit verifies 100/100 snapshot titles, abstract-index
  metadata for 10/100 papers, and exact searchable-chunk joins for all 44,277 selected
  chunks across all 100 papers. The 38-variant literal scan found candidate hits across
  12 papers and 62 chunks (73 variant-paper-chunk matches). Four candidate source
  records have been checked against primary sources and none directly meets the scoped
  criterion. The full 12-paper hit set is not yet adjudicated: an earlier pass mapped
  it to 11 ACL Anthology sources and one external publisher source, but the review was
  interrupted before that pass finished. Do not declare bounded absence until every
  hit that could meet the criterion is reviewed.
- `scripts/phase2_r8_v13_acceptance.py` and
  `benchmarks/phase2/acceptance-v13.toml` are tracked and passed CI. The public freeze
  manifest `benchmarks/phase2/r8-v13-freeze-v1.toml` and private
  `heldout-v13.toml` / `source-alignment-v13.toml` are absent. No validation-only or
  held-out v13 run has occurred and no v13 held-out score exists. The disposable
  Phase 2 PostgreSQL and Qdrant containers were running at this handoff.

### Next actions

1. Resume primary-source adjudication for the remaining paper hits in
   `local-reference/phase2-runs/benchmark-v13/`. Keep question text, candidate IDs,
   source excerpts, and judgments out of tracked files and ordinary logs; never read
   `*origins.json` or spent v12 item-level results.
2. If a direct source-positive is found for the development-only unsupported family,
   correct its source alignment and development labels, then rescore the development
   profiles. If no hit is direct, record the bounded scope and source-review limits.
3. Build the fresh held-out set of 30 families (floor 24, recorded with the failing
   category before pooling) only after source screening, per
   [ADR-0014](../adr/0014-phase2-acceptance-method.md) and
   [sampling plan v3](../reference/phase-2-benchmark-sampling-plan.md): at least 5
   families in each of discovery, specific evidence, table result, comparison and
   filters; at least 4 missing-evidence; 5 direct-positive prose; 8 table-result with 5
   numeric-table; 5 negative/mixed; 24 positive families; 20 direct anchors across 15
   positive families; at most two families per anchor paper. About 22 families need new
   screening. Do not lower floors silently; below 24 needs a further ADR.
4. Pool every declared profile (top 20 papers, top 50 evidence) and pass the
   coverage-only pre-check (at least 95% judged in each top 10, 90% in top 20, no
   selected-profile family below 80% at top 10) by blind source review before freeze.
   Freeze dataset, source alignment, profile/configuration, code, scorer, timing
   procedure, coverage table and the descriptive BM25 difficulty band
   (`r8-v13-freeze-v1.toml`). Run the v13 runner in validation-only mode first, then
   score the frozen held-out set once, on point estimates with bootstrap intervals
   reported. Do not tune against that result.
5. A failed gate seals v13: diagnose on development data with an aggregate-only written
   note before any new set; a replacement needs a validated material change or an
   explicit owner decision. At most two acceptance runs are authorized (v13 and one
   replacement); after a second failure the owner decides via change control. Update the acceptance report, roadmap, operations guidance, README, and source of
   truth as required, then commit/push the verified revision and check hosted CI.

## Guardrails and operating constraints

- The accepted Phase 1 snapshot remains `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` in
  `research_phase1_review`, with 100 papers and 44,277 selected chunks. Keep its database
  and `phase1-e5-small-v2` index separate from disposable tests and Phase 2 variants.
- All previous held-out sets, including v11 and R8 v12, are spent. Never read
  `*origins.json`; do not expose question text, judgments, candidate IDs, or passages in
  tracked files or ordinary logs. New judgments are assistant-reviewed and retain
  source uncertainty.
- Preserve the locked numeric gates, strongest-passage paper aggregation, permissions,
  and exact snapshot boundaries. The user approved one versioned exception: fresh R8
  acceptance-v10 uses a 2,000 ms maximum warm p95; all other gates remain unchanged.
  The 30-second request deadline is separate. Use synthetic or allowlisted development
  data for implementation and tuning. R8 is assessment only after freeze.
- The user delegated Phase 2 implementation and source review, authorized local commits
  and publication through the existing draft PR, and did not authorize merging it.
  Preserve unrelated workspace changes.

## Finalization checklist

1. Preserve the R7 asset inventory and confirm the exact frozen revision in hosted CI;
   do not delete accepted indexes or referenced variants.
2. Freeze implementation, profile, scoring/report versions and timing procedure.
3. R8 v12 failed six gates, so Phase 2 stays open. Complete source-first review of the
   30-family v13 set (ADR-0014), pass the judgment-coverage pre-check, freeze its
   dataset/alignment/configuration, then assess it once. If a gate fails, return fixes
   to development; at most one replacement set is authorized.
4. Reconcile source of truth, roadmap, handoff, README, operations, and acceptance report.
5. Commit and publish the exact revision; verify hosted CI. Do not merge the draft PR.
