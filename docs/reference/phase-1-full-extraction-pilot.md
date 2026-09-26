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

All ten extraction attempts completed without failure. The initial Docling
StandardPdfPipeline run produced 5,944 sections, 113 structured tables, 15,627
evidence units and 9,683 searchable chunks.

After delegated PDF review, four new immutable extraction versions correct five
tables across three papers; a fifth paper's Figure 2 was reclassified from table
evidence to caption-only figure evidence. The current draft contains 5,944
sections, 112 structured tables, 15,628 evidence units and 9,684 searchable
chunks. All eight flagged table records passed review, and the ten-paper draft
validates with no issues at `--minimum-papers 10`. It remains a draft because the
100-paper acceptance gate has not been met.

## Extraction measurements

| Measurement | Result |
| --- | ---: |
| Completed / failed papers | 10 / 0 |
| Sum of per-paper extraction and chunking durations | 845.403 s |
| Longest paper stage (`W7114889968`) | 605.508 s |
| Process high-water RSS | 5,099,646,976 bytes (about 4.75 GiB) |
| Source PDF bytes | 11,587,433 |
| Sections | 5,944 |
| Structured tables | 112 |
| Evidence units | 15,628 |
| Searchable chunks | 9,684 |
| Flagged table checks pending review | 0 (8 passed) |

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

The original rebuild embedded 9,683 permitted chunks in 606 batches. Following
the corrections, the draft was rebuilt again: PostgreSQL and Qdrant both report
9,684 points across 606 batches in `phase1-e5-small-v2`. The corrected draft
passes `snapshots validate --minimum-papers 10` with zero issues. These checks
validate count and reconciliation for the pilot; they do not measure retrieval
ranking or answer quality. The final embedding-model choice remains open for
Phase 2.

## Table review and correction outcomes

<a id="pending-table-review"></a>

The original extraction flagged nine evidence items: eight real tables and one
figure depicting a sample table. The user delegated PDF comparison to the
assistant. Source-linked corrected extractions now replace the affected draft
members without modifying their parent extractions. All eight flagged tables are
reviewed as passed; Figure 2 is represented as figure evidence, not a table. The
current ten-paper draft has no pending review issues.

The table below shows the current extraction version selected in the draft.
Ordinals remain zero-based within each extraction; PDF pages are one-based.

| Paper | Ordinal | PDF page | Current shape / blank cells | Caption or short label | Review | Source PDF |
| --- | ---: | ---: | --- | --- | --- | --- |
| W3217305727 — ColBERTv2 | 4 | 16 (index 15) | 8 × 4; 2 header rows; 11/32 blank | Table 6: MS MARCO passage-cluster examples | Passed | [Open page 16](../../data/artifacts/sha256/62/62d6558f515ef6a62dfb3047f8d79262613c7f13503cdf74d048804e17a6de93.pdf#page=16) |
| W4287887100 — Re2G | 2 | 9 (index 8) | 30 × 7; 2 header rows; 42/210 blank | Table 3: Development Set Results for Re2G Variations | Passed after correction | [Open page 9](../../data/artifacts/sha256/61/6161116555ec492f3004366f7ae43e4c1a0bbddade791a6317fe2c9f63a1ffae.pdf#page=9) |
| W4404782883 — Searching for Best Practices in RAG | 0 | 8 (index 7) | 26 × 14; 2 header rows; 85/364 blank | Table 1: search-practice results | Passed after correction | [Open page 8](../../data/artifacts/sha256/04/045d0bf2712448fcadd850760be8eb92c2576b68643a01f52704d15e13e8456e.pdf#page=8) |
| W4404782883 — Searching for Best Practices in RAG | 1 | 14 (index 13) | 3 × 5; 2 header rows; 4/15 blank | Table 2: query-classifier results | Passed | [Open page 14](../../data/artifacts/sha256/04/045d0bf2712448fcadd850760be8eb92c2576b68643a01f52704d15e13e8456e.pdf#page=14) |
| W4404782883 — Searching for Best Practices in RAG | 6 | 16 (index 15) | 12 × 11; 2 header rows; 29/132 blank | Table 7: retrieval methods on TREC DL19/20 | Passed after correction | [Open page 16](../../data/artifacts/sha256/04/045d0bf2712448fcadd850760be8eb92c2576b68643a01f52704d15e13e8456e.pdf#page=16) |
| W4404782883 — Searching for Best Practices in RAG | 7 | 17 (index 16) | 6 × 11; 2 header rows; 19/66 blank | Table 8: HyDE concatenation results | Passed after correction | [Open page 17](../../data/artifacts/sha256/04/045d0bf2712448fcadd850760be8eb92c2576b68643a01f52704d15e13e8456e.pdf#page=17) |
| W4404782883 — Searching for Best Practices in RAG | 8 | 17 (index 16) | 8 × 11; 2 header rows; 19/88 blank | Table 9: hybrid-search alpha results | Passed | [Open page 17](../../data/artifacts/sha256/04/045d0bf2712448fcadd850760be8eb92c2576b68643a01f52704d15e13e8456e.pdf#page=17) |
| W4404783220 — mGTE | 0 | 4 (index 3) | 8 × 12; 4 header rows; 9/96 blank | Table 1: XTREME-R cross-lingual results | Passed after correction | [Open page 4](../../data/artifacts/sha256/42/42bed71334f634f5ff7f0464866fa5dc843a331daffa8014e9b09a5582aba914.pdf#page=4) |

W7127049495 Figure 2 (page 3, source-table ordinal 1) was reclassified as a
caption-only figure at the same source page. Its new figure evidence is preserved
in the current extraction; no table record remains for it.

Correction lineage in the isolated `research_phase1_review` database:

| Paper | Parent extraction | Current extraction | Correction |
| --- | --- | --- | --- |
| W4287887100 | `a48aea64-1ae4-520e-a80c-2a014ec5cd3d` | `96a754aa-f306-59ff-920a-cc77bfdf9156` | Corrected Table 3 caption/header and six final-row values. |
| W4404782883 | `def27a9e-ef1d-5ef4-bc66-f79a3bd54112` | `871dd093-3473-5e0e-9d3a-0f3b0c90f283` | Rebuilt Table 1 to 14 columns; separated merged metric cells in Tables 7 and 8. Tables 2 and 9 were re-reviewed unchanged. |
| W4404783220 | `5f0d873c-dd8d-54db-a2c8-8ca1ae7ae4d9` | `7106f7f0-6122-5407-9141-ff7f729f05e1` | Rebuilt the grouped header and aligned four mGTE model rows. |
| W7127049495 | `7f57d001-735c-5c54-9d70-48b045267dfd` | `8b70a572-348e-5941-9c55-b1d1c6fc58f7` | Reclassified source Table 1 as Figure 2 caption evidence. |

The ignored local correction manifest has SHA-256
`d3ee7d98c85e99192a3efff46fa2a9779715ef9646400f027ad5a872a8e1b99a`. Each new
extraction configuration records the parent extraction, exact source PDF
checksum, corrected page numbers, reviewer and correction-manifest checksum; the
original extraction outputs remain available. The main numeric comparisons were
checked against the papers' [official ACL proceedings PDF](https://aclanthology.org/2024.emnlp-main.981.pdf),
[Re2G paper](https://aclanthology.org/2022.naacl-main.194.pdf), and
[mGTE paper](https://aclanthology.org/2024.emnlp-industry.103.pdf).

`research-ingest snapshots validate --snapshot-id 0fdaab69-db0d-47ac-95ba-fbe627eddafe --minimum-papers 10`
returns a draft snapshot with 10 members, 9,684 expected chunks, the pinned E5
configuration, and an empty issues list. The snapshot remains a draft until the
approved 100-paper acceptance requirements are met.

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

This report covers ten papers only. The 100-paper pilot still requires user
confirmation of the prepared 100-title membership, exact source/file checks,
acquisition and its own resumable acceptance run. The ten-paper snapshot remains
a draft and does not meet that acceptance gate.
