# Phase 2 benchmark dataset card

| Field | Value |
| --- | --- |
| Dataset | `phase2-benchmark-v4` |
| Snapshot | `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` |
| Status | Assistant review complete; held-out acceptance gate failed two of fourteen limits |
| Active split | `phase2-benchmark-family-splits-v4` |
| Active held-out families | 10 |

## Purpose and scope

This benchmark measures scholarly paper and evidence retrieval over the fixed
100-paper Phase 1 snapshot. It covers discovery, specific evidence, numeric table
results, cross-paper comparisons, filters, and bounded missing-evidence questions.
It is a purposive, corpus-grounded sample for this snapshot. It is not a random
sample of scientific questions and does not support claims about general scientific
retrieval.

| Category | Held-out family count |
| --- | ---: |
| Discovery | 3 |
| Specific evidence | 10 |
| Table result | 3 |
| Cross-paper comparison | 3 |
| Filters | 6 |
| Missing evidence | 3 |

Categories overlap. The ten-family set supports directional paired assessment only.
Question text and family-level records remain private. The tracked report records
manifest hashes and aggregate category counts.

## Data and labels

The active split binds the private question manifest
`sha256:5895890c8a0cd7ab784ce2965e4689d0cb5e003b0dc0e01f33fa27fd76e85df2` and split
manifest `sha256:e1bc1b9225f467f540e7968394aae1f797c9b03b9784c9b44586bfe0270585ae`.
Paraphrases inherit their family split. The held-out set shares the fixed corpus
snapshot with development data while keeping information needs separate.

Candidate relevance uses the approved 0/1/2 scale: 0 is irrelevant, 1 is useful
context or incomplete support, and 2 is direct support for a requested part. Labels
measure relevance rather than whether a finding is favorable. Paper and evidence
labels are separate.

| Reviewed pool | Candidates | Evidence labels 0 / 1 / 2 | Paper candidates | Paper labels 0 / 1 / 2 |
| --- | ---: | --- | ---: | --- |
| Held-out v4 | 418 | 269 / 111 / 38 | 348 | 269 / 69 / 10 |

All 348 paper and 418 evidence candidates have assistant-reviewed labels. A coverage
correction added 99 papers from the saved top-50 outputs pooled across all five frozen
profiles. Profile, rank and score provenance was removed before the supplement was
shuffled and reviewed. All profiles were rescored on the same completed pool. The
retrieval settings and numeric acceptance limits did not change.

## Source mapping and review

The source map has 18 independent source anchors: 12 direct and 6 contextual. Fifteen
anchors map to a reviewed candidate; three remain source-only. Seven evidence
requirement groups describe multi-part needs. Text anchors use the frozen 80% minimum
span-coverage rule. Table anchors require exact target rows with relevant header and
context checks.

An assistant reviewed candidate relevance and checked source evidence against the
accepted local PDFs. These labels are not independent human validation. Candidate
relevance and exact source-span matching are separate measurements.

## Access, permissions and intended use

Question manifests, candidate cards, source offsets, raw pools, profiles, rankings,
and detailed run records remain in the ignored private
`local-reference/phase2-runs/benchmark-v4/` tree. They are not part of the sanitized
card or public repository. The tracked manifests and reports contain aggregate
metadata and hashes only.

Use development judgments for bounded experiments. The v4 held-out result is
unblinded and cannot guide parameter selection or be reused as an unseen test. Report
judged-pool coverage and the snapshot-bounded nature of negative findings. Do not
describe judged recall as recall over all relevant literature or passages.

## Known limitations

- The sample is small, purposive, and tied to one 100-paper snapshot.
- Assistant-only labels can contain source interpretation errors; there is no
  independent human reliability estimate.
- Candidate pooling is bounded and profile-dependent. The paper coverage correction
  pooled the saved top-50 results from the five frozen comparisons; items outside
  that pool remain unjudged.
- Three source anchors do not map to a candidate, even though all returned v4
  evidence candidates are judged.
- The final acceptance gate failed paper nDCG@10 and warm p95; see the
  [acceptance report](phase-2-acceptance-report.md).
- Negative or unsupported findings describe only the documented review procedure
  over this snapshot, not the literature as a whole.
- Ten held-out families support directional paired assessment, not precise
  small-effect estimation.

See the [source coverage audit](../research/phase-2-benchmark-source-coverage-audit.md),
[held-out source audit](../research/phase-2-heldout-question-source-audit.md), and
[evaluation protocol](../plans/phase-2-evaluation-protocol.md) for review and scoring
rules.
