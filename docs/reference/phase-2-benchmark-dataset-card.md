# Phase 2 benchmark dataset card

**Current status:** this card documents the spent v10 set below. The next acceptance
set, `phase2-benchmark-v13`, is pending: under
[ADR-0014](../adr/0014-phase2-acceptance-method.md) it has a target of 30 held-out
families (floor 24), composition floors and a judgment-coverage pre-check defined in
the [v3 sampling plan](phase-2-benchmark-sampling-plan.md). It has no frozen records,
judgments or scores, and this card will be updated when it is frozen.

| Field | Value |
| --- | --- |
| Dataset | `phase2-benchmark-v10` |
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
