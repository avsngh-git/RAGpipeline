# Phase 1 — Learning handoff

Updated: 2026-09-24. P1-01 through P1-12 are complete for the approved ten-paper workflow. The user explicitly delegated the remaining Phase 1 implementation, tests and documentation. P1-13 local checks pass; hosted CI remains. A 33-paper discovery-expansion screening proposal is ready for user approval; its read-only source preflight found 23 candidates with source-level CC BY terms and 10 requiring further rights review. P1-14 then still requires an approved manifest, permitted full-text sources and the acceptance run.

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
   The [P1-14 acceptance report template](../reference/phase-1-acceptance-report-template.md)
   records the eventual 100-paper evidence without fabricating results.
4. **Next decision:** review the [discovery expansion screening proposal](../../manifests/phase1-discovery-expansion-screening-proposal.md).
   It recommends 33 distinct additions to the approved 67, enough for a
   100-paper metadata-screened manifest. See the linked [source and rights
   preflight](../../manifests/phase1-discovery-expansion-rights-preflight.md):
   23 candidates have source-level CC BY terms identified, while 10 need further
   rights review: two ACM journal versions have unconfirmed item-level terms, one accepted
   ACM version carries a personal/classroom-use notice, one coauthor page states
   CC BY-NC-ND for a preprint, two alternate versions are CC BY-NC-SA, three
   publisher versions are CC BY-NC-ND, and RefAI's repository copy needs review. The v2/v3 manifests remain drafts and v1 is unchanged.
   Screening approval does not grant full-text permissions; approve exact
   sources and storage/indexing rights before any new PDF acquisition. P1-13
   hosted CI also remains open until the worktree is committed and CI can run.

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

- P1-09 through P1-12 full ten-paper pilot (agent-verified 2026-09-24): all ten
  approved PDFs extracted successfully to 5,944 sections, 113 tables, 15,627
  evidence units and 9,683 chunks. Nine tables across five papers remain flagged
  for human PDF review; the snapshot is still a draft. The E5-small-v2 rebuild
  indexed and reconciled all 9,683 chunks in 606 batches. The source-artifact store
  uses 11,587,433 bytes against its 2 GiB cap. An audit found that source-PDF
  acquisition had left document availability marked metadata-only; the repository
  now records acquired transactionally, and the ten pilot rows were corrected. The [pilot report](../reference/phase-1-full-extraction-pilot.md)
  records resource and database row-size measurements and the exact review queue.


## Progress protocol

The detailed plan owns task IDs, scope, dependencies and completion evidence.
Update its status table after verified milestones; keep this handoff's next step
current. Label user-reported versus agent-verified outcomes and record code/config
revisions. Do not mark Phase 1 complete without its actual finalized 100-paper
snapshot, acceptance report, recovery/rebuild evidence and passing checks.

Current status: P1-01 through P1-12 are complete for the approved ten-paper
workflow. P1-13 has passed local checks but awaits hosted CI. P1-14 remains gated
on a newly approved 100-paper manifest, source permissions and the acceptance run.

On tested implementation snapshot
`d104e5607d90643fbd0dbb3119fbb7ace8c8e3fc+dirty.sha256:e77d6fd89651a89d0fbeba64335a84a54295b40eee5cd17881e387114e9cae10`,
all **162 tests passed in 4.42 seconds**, including all 15 live PostgreSQL/Qdrant
checks. The disposable `research_test` database was dropped afterward. Ruff
check/format, strict mypy, `pip check`, `pip-audit --skip-editable`, and the
`linux/amd64` Docker build passed. The temporary Docker tag was removed. The
approved `phase1-e5-small-v2` collection retained its 9,683 points after tests.
Hosted CI has not run on this uncommitted worktree.

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
