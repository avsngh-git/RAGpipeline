# Phase 2 — Agent handoff

Updated: 2026-09-29. The earlier v3 assessment failed four frozen gates and v11
passed historically. The one-time R8 v12 assessment has now completed and failed six
of 14 gates; the selected profile passed warm p95 at 894.3 ms against the 2,000 ms
gate. Phase 2 remains open, and v12 is spent and sealed from tuning. Follow the
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
3. R8 v12 failed six gates, so Phase 2 stays open. Return fixes to development data;
   prepare and source-review a new held-out set before a later one-time assessment.
4. Reconcile source of truth, roadmap, handoff, README, operations, and acceptance report.
5. Commit and publish the exact revision; verify hosted CI. Do not merge the draft PR.
