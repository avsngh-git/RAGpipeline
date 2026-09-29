# Phase 2 benchmark dataset card

**Current status:** `phase2-benchmark-v13` (30 held-out families, ADR-0014) was frozen
and scored once on 2026-09-29; it failed 10 of 14 gates and is spent and sealed. The
v13 section below is current. Everything after it, including the v10 fields and
sections, is historical and describes a spent set.

## v13 (current, spent)

| Field | Value |
| --- | --- |
| Dataset | `phase2-benchmark-v13`, dataset SHA-256 `b0f86851da70bd73a9d350ef2972e16e00cb153c394af4026cdede2a997071e8` |
| Alignment | SHA-256 `c6ca4bd8b113456a1b697bacdf5e8db7a6e68a330e8f1a93a4d6d4b3b167169d` |
| Status | Frozen, assistant-reviewed, scored once; failed 10 of 14 gates; sealed |
| Scope | 30 purposive families (25 positive, 5 missing-evidence) on the accepted 100-paper snapshot |
| Categories (overlapping) | Discovery 10, specific evidence 18, table result 16, filters 12, cross-paper comparison 5, missing evidence 5 |
| Positive anchors | 96: 84 source-first builder anchors across 25 families and 12 pool-found label-2 anchors |
| Alignment anchors | 135 table and 2,290 prose anchors, mostly derived label-0 anchors for coverage |

**Review process.** Every builder anchor was verified against the PDF by a separate
verifier. Pooled candidates from the five frozen profiles were judged by blind
reviewers who never saw profile or rank, on the 0/1/2 rubric. Builder-anchor
disagreements in 9 families were resolved in favour of the twice-verified anchors
(decision O11). Eleven cards were unmatchable (segmented or figure chunks) and eight
reranker fallbacks occurred during pooling. All judgments are assistant-reviewed; no
human verification is claimed.

**Coverage.** The pre-check was met with the per-family 80% rule applied to both paper
and evidence. Every profile's paper coverage was 1.000 at top 10 and top 20; evidence
coverage ranged from 0.989 to 1.000 at top 10 and 0.993 to 0.997 at top 20. Every
selected-profile family was 1.000 at top 10.

**Caveats.** Freshness against spent sets v3–v12 cannot be certified, and some anchor
facts were already named in the tracked v13 evidence map (ADR-0014 O3(c)). The set is
purposive and directional, covers one snapshot, and measures ranking only. BM25 fell
outside both descriptive reference bands, so the difficulty flag is set; no gate
changed. Bootstrap intervals and category results are withheld pending a sanitized
extraction. Results are in the [acceptance report](phase-2-acceptance-report.md).

## Historical v10 card

| Field | Value |
| --- | --- |
| Dataset | `phase2-benchmark-v10` (historical) |
| Status | Assistant source review and held-out assessment complete; one frozen operational gate failed |
| Scope | Ten purposive families from the accepted 100-paper snapshot |
| Candidate review | 231 papers and 328 evidence passages; all candidates resolved |
| Positive source mapping | Nine direct source anchors; ten direct pooled-candidate links |
| Family coverage | Seven source-positive and three snapshot-scoped unsupported families |

## Purpose and scope

This benchmark checks paper retrieval, evidence retrieval, source-grounded matching,
filters and operational behavior for the private local research service. Category
counts overlap: discovery (3), specific evidence (10), table result (5), cross-paper
comparison (3), filters (8), and missing evidence (3). These counts are not additive.
The set is purposive and does not represent all scientific questions or measure
corpus-wide recall.

The held-out questions and source identities are private. Public documents report
sanitized aggregates only and do not reproduce question text, paper identities,
passages, candidate rankings or per-family results.

## Data and labels

Candidates were collected from five frozen retrieval profiles and reviewed from
shuffled cards with profile and rank provenance removed. Assistant judgments use the
frozen 0/1/2 rubric. All 231 pooled papers have labels (172 label 0, 50 label 1, nine
label 2); all 328 pooled evidence candidates have labels (149 label 0, 166 label 1,
13 label 2). Unjudged items remain unresolved rather than being treated as irrelevant.

Nine direct source anchors were independently reviewed and mapped to ten candidate
links only when the frozen source-matching rule was met. Prose matching uses the
frozen 80% span-coverage threshold. Table matching requires exact target rows and
validated header and context. Source-found anchors were not inserted into system
rankings. The three unsupported checks are bounded to this snapshot and do not claim
that a topic is absent from the wider literature.

## Source mapping and review

The split, question manifest, source review, source judgments, source map, review
cards and raw profile pools are private, mode-restricted artifacts under
`local-reference/phase2-runs/benchmark-v10-private/`. The directory is ignored by Git.
The sanitized aggregate review audit is
[here](../research/phase-2-benchmark-source-coverage-audit.md).

The question manifest hash is `6606593fa7fb26e2e180d25f0517c41899bd70593c3828c012e2852e257c510f`;
the split hash is `973fc191f2f9f0d4b036edae1aac7e14853736c831a814bfceffaabb297d9379`.
The scoring protocol reports judgment coverage and separates returned-hit behavior
on unsupported queries from positive-retrieval recall. Profile selection uses
calibration/development evidence only; a held-out set is spent after scoring and
cannot guide tuning.

## Access, permissions and intended use

The accepted corpus permits storage and indexing but not public passage display. Raw
questions, candidate text, source mappings and results stay within the trusted
private-local review boundary. This card and the aggregate acceptance report do not
grant access to those artifacts.

## Known limitations

- Ten families provide directional evidence, not precise estimates of small effects;
  ADR-0014 enlarges the next acceptance set to 30 for that reason.
- The set covers one fixed 100-paper snapshot and cannot support claims about the
  whole literature.
- Complete judgment coverage applies to the pooled candidates only.
- Source-anchor recall uses nine reviewed anchors and is not exhaustive corpus recall.
- Unsupported findings apply only to the screened candidates in this fixed snapshot.
- The selected profile passed all quality gates but missed the warm p95 limit; Phase 2
  remains unaccepted.
