# Phase 2 benchmark source and review coverage audit

## Active v9 review — assistant-reviewed 2026-09-28

| Check | Result |
| --- | ---: |
| Held-out families | 10 |
| Paper candidates reviewed | 339 / 339 |
| Evidence candidates reviewed | 496 / 496 |
| Direct source anchors | 9 |
| Direct source-anchor candidate links | 9 |
| Source-positive / unsupported families | 7 / 3 |
| Paper and evidence judgment coverage | 100% / 100% |

All candidates were judged from shuffled cards without rank or profile provenance.
Source anchors were screened independently and mapped only to returned evidence that
meets the frozen source-matching policy. Prose matching requires at least 80% span
coverage. Table matching requires the exact target rows and the frozen header and
context checks. The three unsupported-family reviews found no direct support for
the exact question within this bounded snapshot; adjacent material remains context,
not a positive source match.

The pool and split manifests bind the private questions, source judgments, source
map, cards and five frozen profiles. These hashes and item-level records remain in
the ignored private run directory. No query text, paper identity, passage, candidate
rank, score or per-family result is included here.

This is a bounded, purposive review over the accepted 100-paper snapshot. Complete
candidate judgment coverage means all pooled candidates have a resolved label; it
does not establish corpus-wide recall. See the [dataset card](../reference/phase-2-benchmark-dataset-card.md)
and [acceptance report](../reference/phase-2-acceptance-report.md) for sanitized
aggregate status.
