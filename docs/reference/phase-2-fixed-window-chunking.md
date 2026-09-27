# Phase 2 fixed-window prose chunking

Status: implementation checkpoint 2026-09-27; development comparison pending. The
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

## Verification checkpoint

The focused CPU suite reports 75 passing tests across ingestion, dense indexing,
source matching, deduplication, search contracts, and API schemas. Ruff check and
repository-wide Ruff format checks pass. The snapshot-variant integration test was
extended to verify extraction reuse, cross-section span hydration, and separate
selection identities. It was not run because isolated PostgreSQL and Qdrant test
URLs are not configured in the current environment. Project-wide mypy could not
complete because the recreated Conda environment lacks the declared BM25S and NumPy
packages.

No accepted snapshot or source extraction was changed. A paired development run,
index/storage measurements, and live variant integration remain required by P2-13.
