# Phase 2 benchmark source and review coverage audit

## Active v10 review — assistant-reviewed 2026-09-28

| Check | Result |
| --- | ---: |
| Held-out families | 10 |
| Paper candidates reviewed | 231 / 231 |
| Evidence candidates reviewed | 328 / 328 |
| Direct source anchors | 9 |
| Direct source-anchor candidate links | 10 |
| Source-positive / unsupported families | 7 / 3 |
| Paper and evidence judgment coverage | 100% / 100% |

All candidates were judged from shuffled cards without rank or profile provenance.
Source anchors were screened independently and mapped only to returned evidence that
meets the frozen source-matching policy. Prose matching requires at least 80% span
coverage. Table matching requires the exact target rows and the frozen header and
context checks. The three unsupported-family reviews found no direct support for the
specific scoped request within this bounded snapshot; adjacent material remains
context, not a positive source match.

The question manifest, split manifest, source review, source judgments and source map
are SHA-256 bound in the private run artifacts. Aggregate hashes are: questions
`6606593fa7fb26e2e180d25f0517c41899bd70593c3828c012e2852e257c510f`, split
`973fc191f2f9f0d4b036edae1aac7e14853736c831a814bfceffaabb297d9379`, source review
`d37fb4c045ea3f35862e79afbbe641d43487ee1d35da873a803e55bb9289aa78`, source judgments
`14204316524dd3e35a7f5f1bec6c1b44deacf958c7b697ddb3605c79afe4de49`, and source map
`6e86954fff8e7eacb571ca1a6d139af58ebe21bba027b69b7a80f95f7a3d8811`.
Item-level records remain in the ignored private run directory. No query text, paper
identity, passage, candidate rank, score or per-family result is included here.

The v10 run passed 14 of 15 frozen acceptance gates; only the selected profile's warm
p95 exceeded its limit. This is a bounded, purposive review over the accepted 100-paper
snapshot. Complete candidate judgment coverage means all pooled candidates have a
resolved label; it does not establish corpus-wide recall. See the
[dataset card](../reference/phase-2-benchmark-dataset-card.md) and
[acceptance report](../reference/phase-2-acceptance-report.md) for sanitized results.
