# Phase 2 scoring policy v1

Status: implemented for calibration rankings on 2026-09-26. The evidence-credit
interpretation is assistant-reviewed; no held-out results informed it.

The scorer is `research_platform.evaluation.scoring`; each output identifies
`evaluation-scoring-policy-v1`, its calibration dataset, snapshot, source-alignment
version, and source-matching policy.

## Ranking and relevance

A score is produced per calibration query ID. Paraphrases remain linked to their
question family so later comparisons can aggregate or resample families without
treating paraphrases as independent questions. The scorer uses the supplied one-based
rank values. Rank gaps remain empty; duplicate ranks are rejected. Equal ideal gains
have no ordering effect.

Paper nDCG@10 uses gain `2^label - 1` and credits each paper once, at its earliest
rank. Evidence ranking accumulates canonical source coverage over each result prefix.
A prose anchor is direct when every annotated span meets its frozen threshold: 80% for
ordinary spans and 100% for critical spans. A table anchor is direct when a result
prefix contains at least one mapped target cell, all its associated header cells, and
all required caption, units, or footnote context. A table anchor is fully supported
only when every mapped target cell and its headers are present with the required
context. This keeps cell-level retrieval relevance separate from complete-table
coverage.

Evidence nDCG@10 uses a source-anchor ranking: each judged anchor enters at the
rank where a returned prefix first directly supports it. When multiple new anchors
match at one rank, that rank receives the largest individual gain, capped at label 2.
Other distinct anchors still count toward judged recall and evidence-group coverage.
Duplicate or overlapping hits keep their rank positions and add no gain for an anchor
already credited. The ideal ranking places each unique positive paper or source anchor
at a separate rank in descending gain order. This one-item-per-rank ideal is
achievable for this anchor-level representation, and each actual rank contributes no
more than one item, keeping nDCG in `[0, 1]`. A zero ideal DCG yields an undefined
(`null`) nDCG.

Direct MRR@10 and judged Recall@20/@50 use label-2 judgments only. They deduplicate
papers or source anchors respectively. A source anchor counts for direct MRR and
recall on its first directly supported result. Evidence-group coverage is reported at
10, 20, and 50: a required piece is covered only when one of its label-2 alternatives
is fully supported; the score reports both the fraction of required pieces covered
and the fraction of groups with every piece covered.

Unjudged returned candidates receive zero gain and retain their ranks. Judgment
coverage reports the fraction of returned candidates resolved to a paper or a directly
supported judged source anchor. Interpret nDCG as a conservative judged-pool score
alongside that coverage value. Unsupported-query profiles report returned-hit label
counts. Rejection accuracy requires a separately calibrated acceptance cutoff.

## Scope and denominators

Paper-ID filters define their eligible set directly. Families filtered by year,
document version, or evidence kind require the caller to supply the exact eligible
paper IDs resolved from the accepted snapshot. The scorer validates returned IDs and
applicable hit metadata against that set before calculating denominators. An empty
eligible set is reported separately; recall, MRR, nDCG, and evidence-group coverage
with zero denominators are `null`, not perfect scores.

Metrics retain their numerator and denominator. Query-family outputs keep the
question-family and query IDs so paired summaries can use family as the sampling unit.
