# Phase 1 ten-paper extraction and indexing pilot

**Run date:** 2026-09-24  
**Job:** `9b3095e5-ea11-4812-ab65-787304d4d236`  
**Snapshot:** `0fdaab69-db0d-47ac-95ba-fbe627eddafe` (draft)  
**Processing revision:** `d104e5607d90643fbd0dbb3119fbb7ace8c8e3fc+dirty.sha256:429b569fc52ea7c6c9302b6b90ea625fc4cc59dabf724fad98793b223ec292a3`

## Scope and outcome

This was the approved local ten-paper pilot. The user confirmed that all ten
sampled prose passages, locations, captions and selected table values match the
corresponding PDFs. Each selected PDF's exact artifact association has storage
and indexing permission; public passage display remains disabled. No papers were
acquired beyond the ten-member draft. A status audit found all ten documents still
marked `metadata_only` after their PDFs had been recorded. `record_download` now
promotes availability to `acquired` in the same transaction, and the ten approved
review-database rows were corrected. Ingestion outcome remains a separate status.

All ten extraction attempts completed without failure. Docling StandardPdfPipeline
and the pinned chunking configuration produced 5,944 sections, 113 structured
tables, 15,627 evidence units and 9,683 searchable chunks. Nine tables are marked
for manual PDF association review. The snapshot remains a draft, and validation
with `--minimum-papers 10` reports only those nine review items.

## Extraction measurements

| Measurement | Result |
| --- | ---: |
| Completed / failed papers | 10 / 0 |
| Sum of per-paper extraction and chunking durations | 845.403 s |
| Longest paper stage (`W7114889968`) | 605.508 s |
| Process high-water RSS | 5,099,646,976 bytes (about 4.75 GiB) |
| Source PDF bytes | 11,587,433 |
| Sections | 5,944 |
| Structured tables | 113 |
| Evidence units | 15,627 |
| Searchable chunks | 9,683 |
| Flagged tables pending review | 9 |

Durations are the sum of sequential per-paper stage measurements, not total wall
clock time. The RSS value is the processor process high-water mark. The selected
PDFs remain in the Git-ignored artifact store.

PostgreSQL reports 29,227,416 bytes summed over `pg_column_size` for the selected
section, evidence-unit, table and chunk rows. This is a logical row-size estimate,
not total database disk usage: it excludes indexes, WAL and other database
overhead. The artifact-store inspection reports 11,587,433 bytes used out of the
2,147,483,648-byte configured cap, with no partial files.

## Embedding and index result

The ten-paper pilot used the reversible `intfloat/e5-small-v2` configuration
documented in [ADR-0005](../adr/0005-phase1-embedding-pilot.md) and the
[embedding feasibility report](phase-1-embedding-pilot.md). Its configuration
identity is
`sha256:af4ae74756b20946caee031eefeb26aecad5963a451741ef833c66398f30dbe7`.

The rebuild embedded the 9,683 permitted chunks in 606 batches. PostgreSQL's
expected evidence count and Qdrant's indexed count both equal 9,683. Inspection
after the full integration suite still reports 9,683 points in collection
`phase1-e5-small-v2`. This validates count and reconciliation for the pilot; it
does not measure retrieval ranking or answer quality. The final embedding-model
choice remains open for Phase 2.

## Pending table review

Ordinals are zero-based. Review each listed table against its source PDF with
`research-ingest snapshots review-table` after inspecting it. These are the only
issues returned by ten-member draft validation; do not finalize the snapshot
until they have been reviewed.

| Paper ID | Extraction ID | Table ordinal |
| --- | --- | ---: |
| `W3217305727` | `3c4d6aa9-a861-5598-90c2-fbaa1a6330d0` | 4 |
| `W4287887100` | `a48aea64-1ae4-520e-a80c-2a014ec5cd3d` | 2 |
| `W4404782883` | `def27a9e-ef1d-5ef4-bc66-f79a3bd54112` | 0, 1, 6, 7, 8 |
| `W4404783220` | `5f0d873c-dd8d-54db-a2c8-8ca1ae7ae4d9` | 0 |
| `W7127049495` | `7f57d001-735c-5c54-9d70-48b045267dfd` | 1 |

For example, after checking a table, record its review with:

```bash
research-ingest snapshots review-table \
  --snapshot-id 0fdaab69-db0d-47ac-95ba-fbe627eddafe \
  --extraction-id EXTRACTION_UUID \
  --table-ordinal TABLE_ORDINAL \
  --reviewer "Your name"
```

## Storage cap decision

Retain the existing **2 GiB (`2,147,483,648` byte)** artifact-store cap for the
100-paper pilot. The ten source PDFs use 11,587,433 bytes; a simple tenfold
projection is about 115.9 MB for 100 papers, leaving roughly 18.5 times that
projection under the cap. This is a planning estimate from a ten-paper sample,
not a promise that every 100-paper corpus will fit. The cap is a hard stop for
new acquisition; do not raise it automatically if the approved pilot reaches it.
Disposable-artifact retention periods remain open.

## Verification and gate

The full local suite passed **162 tests in 4.42 seconds**, including all 15 live
PostgreSQL/Qdrant checks, on implementation revision
`d104e5607d90643fbd0dbb3119fbb7ace8c8e3fc+dirty.sha256:e77d6fd89651a89d0fbeba64335a84a54295b40eee5cd17881e387114e9cae10`. Ruff check and format, strict mypy, `pip check`, `pip-audit --skip-editable`
and the `linux/amd64` Docker image build passed. The disposable `research_test`
database and temporary image tag were removed afterward. Hosted CI has not run on
this uncommitted worktree.

This report covers ten papers only. The 100-paper pilot still requires a newly
approved manifest, full-text permission review and its own resumable acceptance
run. The ten-paper snapshot remains a draft and does not meet that acceptance gate.
