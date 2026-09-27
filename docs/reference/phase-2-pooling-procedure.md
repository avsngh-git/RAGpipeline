# Phase 2 benchmark candidate pooling procedure v1

Status: assistant-reviewed 2026-09-27. Question drafts and family assignments were
frozen before pooling. The canonical v2 merge, metadata-stream and cap rules were
finalized before candidate results were reviewed; initial implementation attempts
are superseded and excluded from the canonical review pool. The family assignment is in
[`benchmark-split-v1.toml`](../../benchmarks/phase2/benchmark-split-v1.toml), and
development query drafts are in
[`benchmark-development-questions-v1.toml`](../../benchmarks/phase2/benchmark-development-questions-v1.toml).

## Scope and profiles

Pool only the ten newly drafted development families (`q11`–`q20`) at this step.
Keep calibration families separate. Held-out families (`q21`–`q30`) remain unqueried
until their source-first question drafts are prepared; their scores must not inform
profile, model, or parameter selection.

Run each family against the exact accepted snapshot and its selected chunk set using
these locally pinned profiles:

- `bm25`;
- `dense-e5` and `dense-bge`;
- `hybrid-e5` and `hybrid-bge`;
- `reranked-minilm-e5` and `reranked-bge-e5`.

The two reranked profiles each rerank the same top-50 fused E5 hybrid candidates for
their family. They reorder candidates but cannot add candidates. Use the profile's
existing filters, stage limits, model revisions and source hydration path. Preserve
eligible counts, returned counts, per-stage counts, truncation, exact profile IDs,
and candidate ranks/scores in access-restricted local provenance.

The retained `phase1-e5-small-v2` collection lacks the current per-point
`filter_payload_revision`, so it cannot serve required year-filtered evaluation queries.
Use the separately named `phase2-e5-small-v2-filtered` collection, rebuilt from the
same exact selected chunks on the disposable Phase 2 database clone. The corresponding
profile IDs and hybrid BM25 artifact bind the new collection configuration. Do not
change the accepted E5 collection or accepted review database. BGE already has a
separate filter-ready collection.

## Merge, cap and review view

For each family, union the top 50 evidence results from every profile and deduplicate
exact selected chunk IDs. Do not merge passages by approximate text similarity before
source review; cross-chunk relevance is decided against the frozen source-matching
policy. Preserve every profile/rank/score occurrence in the private origin map.

Review at most 200 unique evidence candidates. Reserve space for independently
source-found candidates first; fill the remaining capacity from ranked profiles using
rank-interleaved round-robin order in the profile order above. Skip IDs already seen
and stop at the cap. If candidates are excluded by the cap, retain their identities
and origins in the private map and record the excluded count and profile coverage.
Independent source-found evidence is stored separately from returned rankings and is
never inserted into a system result list. Select source leads from the accepted-paper
primary-source note, then inspect matching selected text without running any retrieval
profile. For missing-evidence families, scan all 44,277 selected chunks and the 100
paper titles/abstracts with the family topic terms. For q20, first apply its 2024–2025 publication-year filter to all selected papers,
then screen titles, abstracts and selected chunk text for legal-domain terms; prioritize
the legal studies identified in the primary-source note. Preserve terms, corpus depth
and match counts in the private scan record. These
matches are review candidates, not relevance labels or proof of absence.

Build each profile's evidence-derived paper candidates by ordering papers by their
highest-ranked evidence hit (the frozen `strongest_passage` rule), then take the top
20 distinct papers. For reranked profiles, use reranked evidence order. Where a
profile has a lexical stage, also collect the top 20 title/abstract paper-index hits
as a separate metadata candidate stream. Apply publication-year filters to that
stream through exact eligible paper IDs derived from the selected snapshot. The two
reranked E5 profiles reuse the E5 hybrid metadata ranking because reranking changes
evidence order only. Keep branch, profile, rank and score in the private map; show none
of them on review cards. Union and deduplicate paper IDs across all streams. When the
unique paper union exceeds 80, reserve space for independently source-found papers
and apply the same rank-interleaved cap to the remaining profile/branch lists.

Assign opaque candidate IDs independently of profile and rank. Create one shuffled
review card per unique item with source identity and the minimum excerpt/locator
needed to inspect the source. Omit profile names, rank, score, and retrieval stage
from review cards. Keep the reversible candidate-to-source and candidate-to-origin
maps in separate private files under ignored `local-reference/phase2-runs/`.

## Selection-bias record

This is a purposive pool for one accepted 100-paper corpus. Search candidates favor
terms, passages and papers surfaced by the five lexical/dense/hybrid configurations;
reranker profiles add orderings but no new evidence identities. The independent
source-found channel is required to reduce retriever-only selection bias. Pooled
coverage is finite and cannot establish absence outside the snapshot. A missing-topic
judgment must document its corpus-screening procedure, result depth and uncertainty.
