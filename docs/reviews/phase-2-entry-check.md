# Phase 2 entry check — 2026-09-26

**Reviewer:** Codex under the user's Phase 2 delegation  
**Task:** P2-01 — establish entry evidence  
**Result:** Complete. P2-02.1 is the next task.

## Revision, worktree and CI

At entry, `main` was clean and matched `origin/main` at
`0458c9c7f28a5eceac5ca939fe1e17a59e870c1b`. The change from the previously
verified remediation revision `d28e1adc299d6199774c78a2d63cb3eb0870d5ab` touched
`.gitignore`, `AGENTS.md`, `CONTEXT.md` and `README.md`; it did not change
application code. GitHub Actions run [36241133854](https://github.com/avsngh-git/RAGpipeline/actions/runs/36241133854)
completed successfully on the exact entry revision. No local test suite was
rerun for this entry audit.

The audit changes `.gitignore` and restores the sanitized `docs/` tree to Git
eligibility. The docs remain unstaged and uncommitted under the existing
publication workflow. No local manifests, source excerpts, PDFs, credentials,
model weights or generated indexes were added to Git.

## Documentation availability

The root `/docs/` ignore rule hid the authoritative specification, ADRs, plans,
handoffs and reports. It has been removed. `git check-ignore` now returns no match
for the required source-of-truth, Phase 2 handoff/roadmap, ADR-0008 and this report.
The files are present and eligible for the eventual change set; they are not
staged or committed by this work.

## Database target and migrations

The accepted snapshot is in `research_phase1_review`, not the Compose default
`research`. The default database is 9.4 MiB, has migrations 001–012 and contains
no accepted-snapshot row. The review database was 307 MiB, also had migrations
001–012, and contained the finalized 100-paper snapshot.

Before changing its schema, a custom-format PostgreSQL backup was created at
`/tmp/phase2-entry-research_phase1_review-k2gc2x4q.dump` with mode `0600`.
It is 55,188,113 bytes, SHA-256
`526a4dacdf38f1657a4c93dc9bce41fea5d39bd18ae8cb79fb849fd5571c131d`, and
`pg_restore --list` read 15 archive entries successfully. The restore procedure
is to restore this archive into a separate database, validate the accepted
snapshot there, then point the local service at that restored database if
recovery is needed. The archive remains local and excluded from Git.

The repository migration runner was invoked explicitly with
`RESEARCH_PLATFORM_DATABASE_URL` targeting `research_phase1_review`. Migrations
`013_ingestion_job_plans` and `014_snapshot_chunking_configuration` applied.
Migration 014 left `chunking_configuration_id` NULL for all 100 accepted snapshot
items, preserving the legacy selection of their existing chunks. No membership,
evidence, permission or Qdrant data was changed.

## Snapshot, sources and Qdrant

Post-migration `SnapshotRepository.validate` ran with PostgreSQL's default
transaction mode set to read-only. It returned `finalized`, 100 members, 44,277
expected chunks and no issues. All 100 registered source PDFs were reopened by
the content-addressed checksum resolver: 104,636,195 bytes checked and zero
checksum/size failures.

The live, snapshot-filtered Qdrant count and scroll each returned 44,277 unique
evidence IDs. They exactly matched PostgreSQL, with no missing or extra IDs.
Both sorted-ID fingerprints were
`823bd7cd64ed89f555add9ec4967777118b8c1845b4b949e260f88987c9016f8`. The shared
collection contains 53,961 points overall, including the retained ten-paper
draft; collection-wide counts are not a membership check.

## Hardware, services and local storage

- 12 logical CPUs; 7.6 GiB RAM, 4.1 GiB available at measurement; 2 GiB swap,
  with 1.2 GiB in use.
- NVIDIA RTX 3050 Laptop GPU, 4 GiB VRAM; 3,964 MiB free at measurement.
- WSL filesystem: 930 GiB free. Windows C: had 32 GiB free and D: had 244 GiB
  free. The repository is under the WSL home filesystem.
- Running API/PostgreSQL/Qdrant containers used about 22/154/223 MiB RAM.
  PostgreSQL database size was 307 MiB; Compose volumes were about 467 MiB for
  PostgreSQL and 656 MiB for Qdrant. The existing source-artifact directory is
  112 MiB.
- Qdrant reported green status. Its `phase1-e5-small-v2` collection has 53,961
  points, of which 44,277 belong to the accepted snapshot.

The workspace `data/` directory is owned by root and is not writable by the
workspace user. I did not change its ownership or mix Phase 2 outputs into the
2 GiB capped source-artifact store. Private mode-0700 directories were created
under `/tmp/ragpipeline-phase2/` for lexical indexes, model cache and experiments.
Treat these as temporary. Until the durable path is resolved, keep their combined
working allocation below 4 GiB and check disk use before each model/index build;
this is a manual limit, not an application-enforced quota. No model was downloaded
or run during P2-01.

## Next step and limits

Begin P2-02.1 by defining typed search requests bound to an explicit snapshot and
retrieval profile. Local operations must explicitly target `research_phase1_review`;
the running API container still targets `research`. No retrieval code, index build,
source judgment, benchmark or model run was performed during this entry task.
