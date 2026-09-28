# Phase 2 benchmark dataset card

| Field | Value |
| --- | --- |
| Dataset | `phase2-benchmark-v9` |
| Status | Assistant source review and held-out assessment complete; acceptance failed one frozen gate |
| Scope | Ten purposive families from the accepted 100-paper snapshot |
| Candidate review | 339 papers and 496 evidence passages; all candidates resolved |
| Positive source mapping | Nine source anchors; nine direct pooled-candidate links |
| Family coverage | Seven source-positive and three snapshot-scoped unsupported families |

## Purpose and scope

This benchmark checks paper retrieval, evidence retrieval, source-grounded matching,
filters and operational behavior for the private local research service. Category
counts overlap: discovery (2), specific evidence (7), table result (4), cross-paper
comparison (3), filters (2), and missing evidence (3). These counts are not additive.
The set is purposive and does not represent all scientific questions or measure
corpus-wide recall.

The held-out questions and source identities are private. Public documents report
sanitized aggregates only and do not reproduce question text, paper identities,
passages, candidate rankings or per-family results.

## Data and labels

Candidates were collected from five frozen retrieval profiles and reviewed from
shuffled cards with profile and rank provenance removed. Assistant judgments use the
frozen 0/1/2 rubric. Unjudged items remain unresolved rather than being treated as
irrelevant. All 339 pooled papers and 496 pooled evidence candidates have a resolved
judgment.

Positive source anchors were independently reviewed and mapped to evidence
candidates only when the frozen source-matching rule was met. Prose matching uses
the frozen 80% span-coverage threshold. Table matching requires exact target rows
and validated header and context. Source-found anchors were not inserted into system
rankings. The three unsupported checks are bounded to this snapshot and do not claim
that the topic is absent from the wider literature.

## Source mapping and review

The split, question manifest, source review, source judgments, source map, review
cards and raw profile pools are private, mode-restricted artifacts under
`local-reference/phase2-runs/benchmark-v9-private/`. The directory is ignored by Git.
The sanitized aggregate review audit is
[here](../research/phase-2-benchmark-source-coverage-audit.md).

The scoring protocol reports judgment coverage and separates returned-hit behavior
on unsupported queries from positive-retrieval recall. Profile selection uses
calibration/development evidence only; a held-out set is spent after scoring and
cannot guide tuning.

## Access, permissions and intended use

The accepted corpus permits storage and indexing but not public passage display.
Raw questions, candidate text, source mappings and results stay within the trusted
private-local review boundary. This card and the aggregate acceptance report do not
grant access to those artifacts.

## Known limitations

- Ten families provide directional evidence, not precise estimates of small effects.
- The set covers one fixed 100-paper snapshot and cannot support claims about the
  whole literature.
- Complete judgment coverage applies to the pooled candidates only.
- Source-anchor recall uses nine reviewed anchors and is not exhaustive corpus recall.
- Unsupported findings apply only to the screened candidates in this fixed snapshot.
- The selected profile failed the frozen paper nDCG@10 acceptance gate; Phase 2 is
  not accepted.
