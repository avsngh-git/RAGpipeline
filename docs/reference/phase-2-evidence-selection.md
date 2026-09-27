# Phase 2 per-paper evidence selection

Policy ID: `per-paper-evidence-selection-v1`

Evidence search keeps at most the configured number of ranked hits for each paper.
The selector processes by original rank and retains the first `K` hits per paper,
then returns retained hits in global rank order. It preserves original ranks, scores,
source IDs and hit payloads. It does not combine or average scores.

## Configuration

`RetrievalProfile.selection_rules.evidence_per_paper_limit` controls evidence
search. The provisional default is 3 and the maximum is 5. The rule is serialized
into the retrieval profile identity, so searches with different caps have different
profile IDs.

`paper_support_limit` is a separate rule: it controls how many supporting passages
are included inside each paper-level result. It does not replace the evidence-search
cap. Both values currently share the same provisional maximum.

## Omission behavior

Every candidate beyond a paper's cap receives an omission record with chunk ID,
paper ID, original rank, source evidence IDs and reason `per_paper_limit`. The
selection result reports its input candidate count, observed omitted count and
whether this selector omitted any of those candidates. Counts cover the supplied
sequence only; upstream candidate-pool truncation remains a separate signal for the
caller to preserve.

The configured default is a starting point for development. P2-14 will measure
relevance and diversity tradeoffs before any default is frozen.

Implementation: `src/research_platform/search/evidence_selection.py`.
Synthetic behavior: `tests/test_evidence_selection.py`.
