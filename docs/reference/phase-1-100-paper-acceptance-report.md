# Phase 1 — 100-paper acceptance evidence

**Review status:** P1-14 acceptance is complete. Source, extraction-quality,
snapshot-integrity and hosted CI gates passed; the 100-paper snapshot is finalized.

**Report date:** 2026-09-26

**Reviewer:** Codex under user-delegated Phase 1 review

## Run identity

- Membership decision: `sha256:157b7f4f6a132fb39b782d31c819d313c1a6be76a447c7596b54a79c4a32b00d`
- Snapshot: `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` (`phase1-100-assistant-reviewed-pilot-20260925`)
- Snapshot pipeline configuration: `sha256:4d6a82110a37bd21974bd5fcc0aeae416b2996b79082b6645e6d39e7720f5ca7`
- Finalized at: `2026-09-26 09:07:58 UTC`
- Hosted CI: [run 36231611600](https://github.com/avsngh-git/RAGpipeline/actions/runs/36231611600), successful on revision `ed54a046429a7b288830eca0d1a1bcf4e3de87cf`
- Post-finalization validation: 100 members, 44,277 expected chunks, no issues
- Index configuration: `sha256:af4ae74756b20946caee031eefeb26aecad5963a451741ef833c66398f30dbe7`
- Index collection: `phase1-e5-small-v2` (database collection ID `b24f084e-a7dc-4bfc-b234-7eca94311a24`)
- Environment specification: `environment.yaml`, SHA-256 `7d99c1bf4c52c2be80f6b5709e71de9ca15ac6360892d108fea20372cb8e2617`
- Extraction job: `0e6bebc6-706d-49ec-9ad7-296ad48f1f89`, completed; execution profile `100-paper-pilot`
- Extraction job code revision: `ebe1c41602b62c5934fbfe43e51ae765896e3e6e+dirty.sha256:ef4fcbd37efb68242f5aab3529bf36502bc4828b5d3f28c232c3cae695d948ad`
- Snapshot creation code revision: `ebe1c41602b62c5934fbfe43e51ae765896e3e6e+dirty.sha256:b47b72884ed15de9438dd1ad3917148bc87cad65b379048638c9fd9bc8e0e0f5`

## Discovery and membership

The approved v1 set is unchanged. The delegated 100-paper decision contains
10 v1 references, 21 expansion candidates, 51 cited-work candidates and 18
discovery-cache candidates. It has no duplicate selected identities.

The initial bounded discovery retained 2,334 unique candidates and produced a
114-item v1 shortlist; screening included 67 and excluded 47. Discovery used 30
of its 50 allowed request attempts and reached the ten-page cap on all three
queries; the report recorded $0.03 in API cost. Those page caps limit recall. The
later title
screens covered 70 distinct expansion candidates (33 include, 37 exclude), 192
cited-work leads (55 include, 137 exclude), and 80 cache records (43 include, 37
exclude). The 100-paper membership selected 21, 51, and 18 of the included
expansion, cited-work, and cache-screen candidates, respectively, alongside the
10 v1 references. This is a reviewed shortlist, not a recall estimate for all RAG
literature.

Per-item decisions and rationales remain in the local ignored review records:
**v1 screening** (`manifests/phase1-discovery-v1-review.json`, local-only evidence omitted from Git),
**expansion screening** (`manifests/phase1-discovery-expansion-review.json`, local-only evidence omitted from Git),
**cited-work screening** (`manifests/phase1-cited-work-screening-review.json`, local-only evidence omitted from Git),
**cache screening** (`manifests/phase1-discovery-pool-screening-review.json`, local-only evidence omitted from Git), and
the **100-paper membership decision** (`manifests/phase1-100-paper-membership-decision.json`, local-only evidence omitted from Git).
Those `manifests/` files are retained locally but excluded from Git. The accepted
coverage review marks hybrid/dense retrieval and reranking/latency as covered;
chunking/citation remains a gap.

## Source and acquisition review

All 100 selected papers have one exact, acquired PDF. The files on disk, source
URLs, byte sizes, SHA-256 checksums and persisted permission rows were audited
against the isolated `research_phase1_review` database. All 100 permit storage
and indexing; passage display is disabled for all 100. The selected routes are
10 previously reviewed v1 sources, 87 OpenAlex content routes and 3 direct,
version-pinned arXiv routes. The selected files are recorded as 94 published
versions, 3 submitted versions and 3 numbered arXiv versions. All 100 selected
permission rows record CC BY.

One catalog/PDF title difference was manually resolved: the selected PDF title
uses “for” where the catalog title uses “in.” The authors, EMNLP 2023 venue and
DOI match the [ACL Anthology record](https://aclanthology.org/2023.emnlp-main.322/);
the exact PDF checksum and resolution are recorded in the local source review.
Third-party review excluded only RadioRAG PDF pages 21–35 (15 pages); the
authored article and other eligible pages remain in the selected work. See the
**source verification** (`local-reference/phase1-100/pdf-source-verification.json`, local-only evidence omitted from Git)
and **source-review closeout** (`local-reference/phase1-100/source-review-closeout.json`, local-only evidence omitted from Git).

## Acquisition and extraction outcomes

| Outcome | Papers |
| --- | ---: |
| Selected snapshot members | 100 |
| Acquired and checksum-valid PDFs | 100 |
| Metadata-only | 0 |
| Acquisition failed | 0 |
| Final extraction completed | 100 |
| Final extraction partial or failed | 0 |
| Skipped | 0 |

The final snapshot contains 833 tables, 78,377 text evidence units, 5,067 table
row-group units and one figure unit. Its chunk inventory contains 39,209 text
chunks, 5,067 table-row-group chunks and one figure chunk (44,277 total).

The extraction job ran from 2026-09-25 16:30:56 to 17:23:00 UTC (52 minutes,
3 seconds). Persisted extraction-stage attempts total 101: 100 completed and one
failed with `lease_expired`. The same document completed on attempt 2 immediately
after attempt 1 expired. Thus all 100 selected papers have a completed final
extraction. The maximum recorded process peak RSS was 5,548,874,576 bytes
(about 5.17 GiB); peak VRAM was not recorded. The 100-paper run used the standard
PDF pipeline, not the VLM review aid.

## Extraction quality review

The fixed thresholds and sampling rules are in the
[extraction comparison protocol](phase-1-extraction-comparison.md). The ten-paper
reference comparison reported 100% ordered prose-token coverage, 100% page
provenance accuracy across 366 elements and 98% mean caption-token coverage.
Those are reference-set results and are not a claim that all prose in 100 papers
was manually checked.

For the 100-paper snapshot, 83 flagged tables and 20 ordinary-sample packet items
were source-reviewed; one of the 103 packet items was a figure and was
reclassified as figure evidence. The 102 table reviews checked caption, page,
header/value association and representative source cells. Eight source-linked
correction sets are listed by digest in the
**table review record** (`local-reference/phase1-100/table-review-results.json`, local-only evidence omitted from Git).

The weighted unique numeric-value check passes at **269/269 (100%)** across 95
reviewed tables with numeric sample values. Every one of those tables is above
the 90% per-table threshold. Seven other reviewed tables had no numeric result
cell among their selected sample checks, so they do not enter the numeric
denominator; their structure, caption and page were still reviewed. Corrected
PDF text that had fused adjacent values was split using the reviewed source grid.
The score counts each distinct expected value once per table and checks its
presence in that table's final extracted grid. It does not claim every cell in
all 833 tables was manually verified.

Figure-pixel interpretation and equation-region accuracy remain outside this
phase. No new prose annotations were added for the 90 non-v1 papers; prose quality
evidence remains the separately identified ten-paper reference sample.

## Storage, recovery and index integrity

The artifact store grew from 11,587,433 bytes for the ten-paper set to
116,492,245 bytes after selecting 100 papers, within the configured
2,147,483,648-byte (2 GiB) hard cap. The artifact database contained 100 source
PDF records and zero artifacts without a document association. All 100 PDF files
were reopened through their registered content-addressed paths and passed
checksum and byte-size validation.

The snapshot index was rebuilt with the configured E5-small-v2 model in 2,768
batches. Rebuild duration was not persisted. A snapshot-filtered Qdrant scroll
and PostgreSQL comparison found 44,277 expected and observed evidence IDs with
matching SHA-256 fingerprints:

`823bd7cd64ed89f555add9ec4967777118b8c1845b4b949e260f88987c9016f8`

The shared Qdrant collection contains 53,961 points in total: 44,277 for this
100-paper snapshot and 9,684 for the retained ten-paper snapshot
`0fdaab69-db0d-47ac-95ba-fbe627eddafe`. Reconciliation is snapshot-scoped, so
the earlier pilot points are retained intentionally.

The accepted snapshot is stored in the isolated `research_phase1_review`
PostgreSQL database. The default local application database, `research`, does not
contain this snapshot. Set the connection URL to the review database when running
its validation command. The read-only validation returned no issues:

```bash
RESEARCH_PLATFORM_DATABASE_URL=postgresql://research:research@localhost:5432/research_phase1_review \
  conda run -n sci_research_agent python -m research_platform.ingestion.cli snapshots validate \
    --snapshot-id 4b11fab3-d4a5-4e7a-a58e-8654accf2c6c \
    --minimum-papers 100
```

## Decision and acceptance outcome

The delegated 100-paper membership is accepted; source checks, table sample,
recovery, storage bound, rebuild and snapshot validation are recorded above. After
hosted CI passed, snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` was finalized
in the isolated `research_phase1_review` database by Codex under the user's
Phase 1 delegation. Post-finalization validation reports 100 members, 44,277
expected chunks, the pinned E5 index configuration, and no issues. CI run
36231611600 passed on revision `ed54a046429a7b288830eca0d1a1bcf4e3de87cf`.
The README documents source access, the 10/100 execution profiles, review-database
target, resume/retry, cleanup, index rebuild, and benchmark reproduction. P1-14
acceptance is complete; see the [learning handoff](../plans/phase-1-learning-handoff.md).
