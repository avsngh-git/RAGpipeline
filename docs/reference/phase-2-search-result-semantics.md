# Phase 2 search result semantics

Status: implemented 2026-09-27 under the approved Phase 2 delegation. See
[ADR-0011](../adr/0011-explicit-search-result-semantics.md).

## Eligibility and result status

Every search response reports `eligible_count`: the exact number of records inside
the resolved snapshot that satisfy the requested filters, before ranking and page
limits. The unit is papers for paper and metadata search, and evidence records for
evidence search. Counts come from the authoritative lexical row selection or the
validated snapshot index, not from the number of returned hits.

The response derives one `result_status`:

| Status | Meaning |
| --- | --- |
| `no_eligible_records` | No snapshot records satisfy the requested filters (`eligible_count == 0`). |
| `no_candidates_returned` | Eligible records exist, but the requested search returned no candidate. A lexical query with no positive term matches is one example. |
| `ranked_candidates` | One or more candidates were returned in retrieval order. |

An empty filter scope is therefore distinct from an eligible scope with no returned
lexical hits. Dense and hybrid branches also carry exact eligibility counts. Hybrid
search fails closed if the lexical and dense branches resolve different counts for
the same snapshot and filters.

## Interpretation and thresholds

Every response reports `ranking_interpretation: ranking_only`. A returned candidate
is not an answerability decision, relevance judgment, or verified claim-to-evidence
mapping. Raw lexical, dense, fusion and reranker scores remain method-specific values;
they are not probabilities.

No score/relevance cutoff is applied. Unsupported questions can still return ranked
candidates. A future cutoff may be introduced only after calibration on development
judgments for the exact effective retrieval mode and profile, and must be versioned
with that profile before held-out evaluation. Until then, unsupported-query evaluation
reports retrieved-hit characteristics without inventing rejection accuracy.

The versioned local evaluation attempt record stores the eligible count, result
status and ranking-only interpretation alongside requested/effective mode, profile,
filters and returned IDs.
