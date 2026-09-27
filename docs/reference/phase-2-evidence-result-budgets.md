# Phase 2 evidence result budgets

Policy ID: `evidence-result-budget-v1`

Evidence results are bounded by request item count and by profile-bound character and
token budgets. The provisional profile defaults are 12,000 text characters and 4,000
tokens, with hard maxima of 24,000 characters and 8,000 tokens. A result page is
limited to at most 50 top-level evidence hits. Paper search is limited to 50 papers,
with at most five supporting hits per paper; the same text/token budgets are applied
once across the complete page of supporting hits.

## Token counting

The profile selects `unicode-token-v1`: each Unicode word run and each individual
non-whitespace punctuation mark counts as one token. The tokenizer ID and both
budgets are included in the canonical retrieval profile. This is a deterministic
response-size measure, not a model-token estimate or a quality threshold.

## Whole-unit selection

Candidates are considered by original rank and stable chunk ID. The selector keeps
an entire hit only when its text and any structured table context fit the remaining
budgets. It counts the readable hit text and all returned table strings, including
caption, units, footnotes, header values/labels, and selected cell values/labels.
Source IDs and other non-text metadata are not part of these text budgets.

When a hit does not fit, the selector omits the whole source-linked unit and records
its chunk ID, paper ID, original rank, source evidence IDs, and every exceeded limit.
It continues to lower-ranked candidates that may fit. It never clips cell values,
rows, or table context. Existing oversized-cell evidence units are source-linked
subdivisions and can fit independently. Ranks, scores and retained hit payloads are
unchanged.

The selection result reports selected hits, observed candidate and omission counts,
character/token use, warnings, and whether an upstream pool was already truncated.
When the input pool is complete, the omission count is exact. When a retrieval stage
truncated its pool, the count covers only observed candidates and the result remains
marked truncated.

## Configuration

`SelectionRules.evidence_result_character_budget`,
`SelectionRules.evidence_result_token_budget`, and
`SelectionRules.text_budget_tokenizer` are serialized in retrieval profile schema
2. Changing them changes the retrieval-profile ID. The defaults remain provisional
until P2-14 measures quality, diversity and runtime tradeoffs.

Implementation: `src/research_platform/search/evidence_budgets.py`.
Synthetic behavior: `tests/test_evidence_budgets.py`.
