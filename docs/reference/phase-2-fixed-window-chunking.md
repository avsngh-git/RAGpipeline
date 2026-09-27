# Phase 2 fixed-window prose chunking

Status: P2-13 complete 2026-09-27; dense-E5 development comparison completed. The
tracked baseline is
[phase2-fixed-window-chunking-v1.example.toml](../../configs/phase2-fixed-window-chunking-v1.example.toml).

## Frozen implementation choices

The baseline uses the same extracted prose, tokenizer, token budget, and table
renderer as the current section-aware configuration. Its starting text settings are
480 tokens per window and 64 tokens of overlap; tables remain capped at six data
rows per group. The tokenizer identity is E5-small-v2 with the existing pinned
revision and preprocessing identity.

Sections are sorted by extraction ordinal and joined by two newlines. Those
synthetic separator characters carry no PDF locator. Each chunk stores the
intersection with every source section as half-open source and chunk character
ranges, the heading path, and the source location available for that section.
A chunk crossing sections has null legacy section offsets and an empty legacy
single-location value. It never inherits one page or bounding box for the entire
chunk.

The fixed-window configuration has schema version 2 and a separate implementation
revision. The original section-aware serialization and identity remain unchanged.
Both strategies reuse the same extraction checkpoint; chunking a variant selects
new chunk IDs under a new configuration identity. Tables pass through the existing
row-group chunker with the same settings and source corrections.

Source spans are persisted in existing chunk JSON metadata. Dense query hydration
returns validated source spans from PostgreSQL. Search result contracts expose the
same typed representation. Evaluation source matching and evidence deduplication
union all section-local ranges, including overlaps, by their original section and
offsets.

## Verification and paired development result

The focused fixed-window, extraction-reuse, source-deduplication, and matcher unit
checks pass (46 tests). The live synthetic rechunk test passes against the disposable
PostgreSQL/Qdrant services (1 passed). The variant preserves the accepted extraction
rows and all 5,068 table/figure chunk IDs; it selects 3,427 fixed-window prose chunks.

The source-span fairness audit maps 27 reviewed positive prose candidate intervals
to the exact accepted source text. Every anchor has full coverage under both chunk
sets. All 27 full-span anchor inputs fit within 512 tokens for both pinned E5 and BGE
tokenizers. All 301 fixed-window text chunks in anchor-bearing papers also fit under
both tokenizers.

On q11–q19 with identical dense E5 revision, filters, and top-50 limit, the
section-aware/fixed-window source-anchor recall counts were 2/1 at rank 1, 4/4 at
rank 5, 7/6 at rank 10, 9/9 at rank 20, and 13/13 at rank 50 (27 anchors across
seven positive families). q15 and q19 contribute no positive prose anchor. This
small comparison does not show a fixed-window quality improvement. The tracked
[paired audit](../research/phase-2-fixed-window-source-fairness-audit.md) records
metric definitions, profile identities, private artifact hashes, and limitations.

The paired run used an isolated test database and Qdrant. The parent E5 vectors were
read-only copied into the isolated Qdrant collection and reconciled against the exact
44,277 selected IDs so the same year filters could run. The accepted database and
index were not changed. Raw ranks and scores, plus mode-0600 scripts/results, remain
under ignored `local-reference/phase2-runs/fixed-window-20260927/`. No held-out
result or q20/q21 result was used.
