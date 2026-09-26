# Phase 1 — Learning handoff

Updated: 2026-09-25. P1-01 through P1-12 are complete for the approved ten-paper workflow. The corrected draft contains 5,944 sections, 112 tables, 15,628 evidence units and 9,684 chunks; all eight flagged table checks passed, and validation reports no issues. The current worktree passes 188 tests in 3.59 seconds, including all 15 live service checks, Ruff check/format, strict mypy, the migration step, pip check, pip-audit and the Linux AMD64 Docker build. Baseline hosted CI passed on `ebe1c41602b62c5934fbfe43e51ae765896e3e6e` ([run 36053054222](https://github.com/avsngh-git/RAGpipeline/actions/runs/36053054222)); hosted CI has not run on the current worktree.

Three assistant title screens are finalized under the user’s Phase 1 delegation: 70 expansion candidates (33 include, 37 exclude), 192 cited-work leads (55/137), and 80 cache records (43/37). The current pool has at most 144 preliminary source routes. Ten PDFs are associated with approved v1; five private NC-ND/NC-SA PDFs are stored locally but remain unassociated with the accepted 100-paper set. They do not reduce the 90 accepted-paper gap. See the [rights preflight](../../manifests/phase1-discovery-expansion-rights-preflight.md) and [NC acquisition inventory](../../manifests/phase1-discovery-expansion-nc-acquisition.json).

Four of the ten authorized expansion follow-ups remain unacquired or unresolved; one is the Springer route that returned HTML and three are ACM/PMC candidates needing separate source paths. The accepted [ADR-0007](../adr/0007-bounded-direct-source-pdf-downloads.md) enables bounded Springer Nature, version-pinned arXiv and Glasgow Eprints routes; each item still needs source-specific permission evidence. The OpenAlex default remains CC BY/public domain. The ten-paper pilot’s nine original flagged items were visually compared under delegation. Five tables were corrected across three papers; one figure was reclassified in a fourth paper; all eight flagged tables passed. The delegated 100-paper set is now acquired and extracted. Exact PDF, version, checksum and permission checks passed for all 100 files; all initial source-review checks are closed in the linked closeout. The 100-paper table sample and snapshot validation also pass. P1-14 remains open only for current-worktree hosted CI and formal snapshot finalization.

## Start here

1. Follow AGENTS.md and read the authoritative
   [source of truth](../agents/scientific-research-platform-source-of-truth.md).
2. Read the [approved Phase 1 task checklist](phase-1-corpus-ingestion.md).
3. **P1-01 through P1-08 are complete.** The bounded P1-04 discovery run has
   completed. Manifest v1 is approved with 67 included and 47 excluded candidates.
   The approved coverage statuses are hybrid/dense `covered`, reranking/latency
   `covered`, and chunking/citation `gap`. Review the [approved manifest](../../manifests/phase1-discovery-v1.json),
   [decision record](../../manifests/phase1-discovery-v1-review.json),
   [screening rationale](../../manifests/phase1-discovery-v1-screening-proposal.md),
   and [yield/coverage report](../../manifests/phase1-discovery-v1-report.json).
   The project API key is already in ignored `.env`; keep it out of Git and chat.
   P1-05 imported the approved candidates into the isolated review database and
   recorded metadata outcomes for all 1,166 distinct unresolved OpenAlex targets.
   P1-06 reviewed current OpenAlex
   and arXiv access terms; 28 records pass the metadata availability/license
   prefilter. The user approved the [ten-paper sample](../../manifests/phase1-discovery-v1-pdf-reference-proposal.md)
   for local storage and indexing. Ten PDFs are stored outside Git; review the
   [acquisition inventory](../../manifests/phase1-discovery-v1-pdf-acquisition.json).
   Use the [compact PDF review index](../../manifests/phase1-discovery-v1-pdf-review.md).
   The user checked titles and page locations in the local PDFs and confirmed that
   all ten prose/table samples match. The W4410600121 metric-label mismatch was
   corrected, and the user accepted the updated values. P1-07 is complete. P1-08 selected
   Docling standard for extraction and a review-only VLM aid for flagged tables. The
   reversible E5-small-v2 pilot is complete; the final embedding choice remains open
   for Phase 2. Review the [local sample packet](../../local-reference/phase1-discovery-v1/review-draft.md)
   using the [reference protocol](../reference/phase-1-reference-protocol.md).
   The [100-paper acceptance report](../reference/phase-1-100-paper-acceptance-report.md)
   records the observed pilot results and the remaining hosted-CI gate.
4. **P1-14 status:** the assistant accepted the [100-title membership](../../manifests/phase1-100-paper-membership-decision.json) on 2026-09-25 under the user's explicit delegation. The set is 10 v1 papers plus 21 expansion, 51 cited-work and 18 cache-screen candidates; the approved v1 remains unchanged. All 100 selected PDFs are acquired, checksum-valid and linked to persisted storage/index permission evidence. The [source-review closeout](../../local-reference/phase1-100/source-review-closeout.json) resolves the three checks listed in the initial source-route review. The [100-paper acceptance evidence report](../reference/phase-1-100-paper-acceptance-report.md) records extraction, table review, recovery and index reconciliation. Six privately stored follow-up PDFs remain unassociated and do not count toward acceptance. No further copyright decision is pending. The 100-paper snapshot remains a draft until hosted CI runs on the current worktree; its last recorded hosted run is the baseline. The current worktree passed 188 local tests, including all 15 live service checks; Ruff check/format (92 files), strict mypy (40 source files), migration, `pip check`, `pip-audit` and Linux AMD64 Docker build also passed.

Do not repeat the completed planning interview. Corpus scope, 10/100-paper
milestones, text/table requirements, manually finalized snapshots, one active
ingestion process and unresolved citation preservation are already approved.
The parser/model strategy and extraction thresholds are recorded in ADR-0004 and
the comparison report. E5-small-v2 is selected only as the reversible ten-paper pilot model; the final
embedding choice remains open for Phase 2. The 2 GiB artifact cap is set from the
measured ten-paper footprint; disposable retention and 100-paper corpus approval
remain open. Ask only about genuinely unresolved choices.

## Working with the user

The user initially preferred to write the coding tasks while learning Python.
On 2026-09-23 the user explicitly delegated the remaining Phase 1 tasks and
implementation to the assistant. Continue implementation, tests and documentation
autonomously. Preserve existing worktree changes. Do not commit, push, create
GitHub issues or start large model/full-text acquisitions without reaching the
relevant source-permission and human-review gates. The ten-paper PDF reference samples have user confirmation; the versioned
manifest is approved. Use the issue-tracker instructions if ticket publication is later
requested.

## Repository facts at handoff

- P1-01 was verified against code revision
  `d104e5607d90643fbd0dbb3119fbb7ace8c8e3fc`; the worktree was clean and
  `main` matched `origin/main` at verification.
- Hosted [CI run 35852371358](https://github.com/avsngh-git/RAGpipeline/actions/runs/35852371358)
  succeeded on that exact revision. All workflow steps completed, including
  service integration tests and the Docker build.
- The Phase 0
  [audit](../reviews/phase-0-audit-2026-09-23.md) and
  [Phase 0 handoff](phase-0-learning-handoff.md) record the local fixes.
- Existing foundations: Conda environment/lock, package, typed settings,
  FastAPI health/readiness, logging/errors, PostgreSQL/Qdrant Compose,
  migration runner and unit/API/live-service test infrastructure.
- Discovery, permission-gated acquisition, source-linked extraction/evidence,
  deterministic chunking, model-neutral Qdrant rebuild, a generic resumable runner,
  job leases, retryable preview-first artifact cleanup, shortlist review reporting,
  snapshot inspection, immutable snapshot finalization and a bounded local preview of
  draft evidence are implemented with local and isolated live tests. The preview
  requires storage permission for the extraction source artifact. The bounded P1-04
  OpenAlex metadata discovery has now run;
  the approved ten-paper reference PDFs are acquired. Scaling acquisition beyond
  that sample remains gated. The user completed the ten-paper reference review;
  P1-08 chose the standard parser plus review-only vision aid. E5-small-v2 was
  selected for the reversible ten-paper index pilot; the final model remains open
  pending Phase 2 retrieval evaluation.
- Preserve applied `001_initial.sql`. Migrations `002` through `012` add the
  Phase 1 schema; the runner applies each migration and its version atomically
  under a PostgreSQL advisory lock. Empty-database, Phase 0 upgrade, concurrent
  and repeat migration/integration tests pass; the persistent Compose `research`
  database remains untouched.
- Compose bind-mounts Git-ignored `data/artifacts` to `/app/data/artifacts` so
  host and container ingestion commands share persistent source PDFs.
- Unresolved external citations, source-artifact permission evidence, extraction
  lineage, resumable stage attempts, immutable snapshots and index reconciliation
  now have schema/repository support. [ADR-0003](../adr/0003-ingestion-persistence.md)
  records the accepted persistence and indexing decisions.
- Agent-verified runtime snapshot (2026-09-23): `environment-linux-64.lock`
  SHA-256 is `7e72ec479c6820d8bad52ad8662f9496fedb2dfe41681b5ec1cf94926f2865ce`;
  `sci_research_agent` uses Python 3.12.14, Conda 26.7.1, Ruff 0.16.7,
  mypy 2.3.1 and pytest 9.1.1. Docker is 29.8.0; Compose is 5.5.1. The
  active base shell used Python 3.14.7; use the project environment for work.
- Agent-verified resource snapshot (2026-09-23): Ubuntu 24.04 under WSL2 had
  7.6 GiB total and 4.2 GiB available RAM. The RTX 3050 Laptop GPU had 4,096
  MiB total and 3,964 MiB free VRAM. The Ubuntu WSL distribution is stored on
  host volume D: with 264.6 GiB free; Docker's WSL data is stored on C: with
  40.7 GiB free. `df` showed 949 GiB free in the WSL filesystem. Remeasure
  before the pilots; the parser feasibility pilot has since completed. The P1-01
  profile ceilings are recorded in the corpus ingestion plan.

- P1-08 parser run (agent-verified 2026-09-24): 19 reviewed pages from 10 PDFs;
  280 pages in those documents. Standard pipeline 30.437 s, 2,937,028,608 bytes
  peak RSS, 1,868,562,432 bytes peak CUDA reserved; VLM 908.855 s,
  2,317,397,616 bytes peak RSS, 1,023,410,176 bytes peak CUDA reserved. Both had
  zero conversion failures and 100% provenance on annotated elements. The score
  details, dependency/model pins and quality limits are in the linked P1-08 report.
- Pre-comparison resource recheck (agent-verified 2026-09-24): WSL reported
  7.6 GiB RAM total and 3.7 GiB available; the RTX 3050 Laptop GPU had 3,964 MiB
  free VRAM. D: had 265 GiB free and Docker's C: volume had 37 GiB free. The
  WSL filesystem view had 949 GiB free and is not physical capacity. The ten
  source PDFs use 11,587,433 bytes. The 19-page standard comparison output used
  1,018,293 bytes; this partial comparison is not the complete 10-paper storage
  footprint used to set the final cap.

- P1-09 through P1-12 full ten-paper pilot (agent-verified 2026-09-24; corrected 2026-09-25): the initial run produced 5,944 sections, 113 tables, 15,627 evidence units and 9,683 chunks. Source-linked corrections now yield 5,944 sections, 112 tables, 15,628 evidence units and 9,684 chunks. All eight flagged tables passed, and the figure misclassified as table evidence was reclassified. PostgreSQL and Qdrant reconcile 9,684 chunks across 606 batches; ten-paper snapshot validation returns no issues. The snapshot remains a draft because the 100-paper gate is unmet. The source-artifact store uses 11,587,433 bytes against its 2 GiB cap. An audit also fixed acquisition status so recorded PDFs promote document availability to acquired transactionally. See the [pilot report](../reference/phase-1-full-extraction-pilot.md) for resource measurements and correction lineage.


## Progress protocol

The detailed plan owns task IDs, scope, dependencies and completion evidence.
Update its status table after verified milestones; keep this handoff's next step
current. Label user-reported versus agent-verified outcomes and record code/config
revisions. Do not mark Phase 1 complete without its actual finalized 100-paper
snapshot, acceptance report, recovery/rebuild evidence and passing checks.

Current status: P1-01 through P1-12 are complete for the ten-paper workflow. The delegated 100-paper membership is recorded, all 100 selected PDFs passed exact source/checksum/permission review, and the 100-paper extraction completed for every member. The manual sample covers 83 flagged tables and 20 ordinary-sample packet items; one item was reclassified as a figure, and all 269 sampled unique numeric values were present after source-linked corrections. Snapshot validation in `research_phase1_review` reports no issues, and snapshot-filtered PostgreSQL/Qdrant evidence IDs match (44,277). The default `research` database does not contain this snapshot; point `RESEARCH_PLATFORM_DATABASE_URL` at the review database for its CLI commands. The [100-paper acceptance report](../reference/phase-1-100-paper-acceptance-report.md) and [source closeout](../../local-reference/phase1-100/source-review-closeout.json) record these results. Current-worktree local checks passed 188 tests in 3.59 seconds, including all 15 live service checks; Ruff check/format (92 files), strict mypy (40 source files), migration, `pip check`, `pip-audit` and the Linux AMD64 Docker build also passed. Baseline hosted CI run [36053054222](https://github.com/avsngh-git/RAGpipeline/actions/runs/36053054222) passed, but hosted CI has not run on the current worktree. Therefore the 100-paper snapshot remains a draft and P1-14 remains in progress. Six additional private follow-up PDFs remain unassociated and outside the accepted set.

On code revision `ebe1c41602b62c5934fbfe43e51ae765896e3e6e`, all **162 tests passed in 3.76 seconds**, including
all 15 live PostgreSQL/Qdrant checks. The disposable `research_test` database was
created for the run and dropped afterward. Ruff check/format (91 files), strict
mypy (37 source files), `pip check`, `pip-audit --skip-editable`, and the
`linux/amd64` Docker build passed; the temporary image tag was removed. The audit
found no known vulnerabilities and excluded two editable local distributions. The
approved `phase1-e5-small-v2` collection remained green with 9,683 points. The
[hosted CI run 36053054222](https://github.com/avsngh-git/RAGpipeline/actions/runs/36053054222) succeeded on this exact baseline revision. Later work added the direct-source adapter, source-linked extraction corrections and tests, so hosted CI does not cover the current worktree. The current worktree passed 188 local tests, including all 15 live PostgreSQL/Qdrant checks, plus Ruff check/format (92 files), strict mypy (40 source files), migration, `pip check`, `pip-audit` and Linux AMD64 Docker build; hosted CI remains the outstanding gate.

The bounded P1-04 live discovery completed on 2026-09-24 in the isolated local
`research_phase1_review` database: 30 request attempts out of the 50-attempt
ceiling, with `$0.03` reported API usage. It retained 2,334 unique candidates and
created a 114-candidate v1 manifest. The user approved all candidate-level
decisions: 67 include and 47 exclude, plus the coverage assessment (hybrid/dense
covered, reranking/latency covered, chunking/citation gap). Manifest v1 is approved.
See [the manifest](../../manifests/phase1-discovery-v1.json),
[review decisions](../../manifests/phase1-discovery-v1-review.json),
[screening rationale](../../manifests/phase1-discovery-v1-screening-proposal.md),
[the report](../../manifests/phase1-discovery-v1-report.json), and the
[P1-04 evidence in the plan](phase-1-corpus-ingestion.md#p1-04-live-discovery-and-review-evidence-2026-09-24).
An attempted export against the default `research` database applied migrations
002–012 at 10:25 UTC; it found no manifest and wrote no candidate records there.
Screening data stays in `research_phase1_review`. The key remains local in ignored
`.env`; it is absent from `.env.example` except for the placeholder. At the time of
that export, no full-text acquisition had occurred; the later approved ten-paper
acquisition is recorded under P1-06/P1-07 below. P1-05 then imported the approved
67-paper manifest in `research_phase1_review`: 328 distinct authors, 114 metadata-only source locations,
49 resolved citation edges and 1,501 unresolved endpoints. A 50-attempt bounded
The initial OpenAlex batch found metadata for 48 of 50 targets and marked 2 not
found. A resumable continuation checked the remaining 1,116 targets: 954 of all
1,166 returned metadata and 212 were not found. The pending target queue is empty;
all unresolved citation endpoints remain preserved pending identity resolution.
Three sampled not-found records returned HTTP 404 on independent recheck. Singleton
lookups left the free daily API balance unchanged. P1-06 reviewed current OpenAlex
and arXiv access terms.
The 67-paper preflight found cached PDFs for 42 works and 28 works that also match
the default explicit-license allowlist; those prefilters were not permission
approvals. On 2026-09-24 the user approved a ten-paper set for local
storage/indexing. All ten were rechecked for current cached-PDF availability,
CC BY license and published version, then acquired into Git-ignored storage.
The [inventory](../../manifests/phase1-discovery-v1-pdf-acquisition.json) records
checksums and permission evidence. Ten successful requests used $0.10 of free
daily allowance; one failed local write used another $0.01. Prepaid balance
remained $0. The user-reported title/page-location check is complete, and the user
confirmed all ten prose/table samples match. The W4410600121 metric labels were
corrected and accepted. P1-07 is complete. P1-08 compared the standard and VLM
pipelines on 19 annotated pages; the standard pipeline is selected for automatic
extraction and VLM remains review-only for flagged tables. The ten samples and
parser outputs are stored in ignored [local-reference data](../../local-reference/phase1-discovery-v1/review-draft.md).
Public passage display is disabled.
