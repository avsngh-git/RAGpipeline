# Failure analysis

This page summarizes measured retrieval, agent, answer, ingestion, and security
failures recorded in the repository. The measurements use different datasets and
denominators, so the table below groups recurring failure classes rather than ranking
them as if they came from one comparable test.

## Summary

| Failure class | How often | Stage | Evidence | Status |
| --- | --- | --- | --- | --- |
| Direct evidence is missed at shallow ranks | The selected v14 profile found 72 of 126 direct source anchors at rank 10 and 82 of 126 at rank 50. | Retrieval | [Phase 2 acceptance report](phase-2-acceptance-report.md) | Retrieval gates passed, but the report calls the result directional; dense gte ranked papers better than the selected profile. |
| Planner stays on local paper search | In the natural Phase 3.5 pass, 10 runs made 19 `search_papers` and 5 `search_evidence` calls, with no discovery or ingestion requests. | Planning | [Phase 3.5 evaluation](phase-3.5-evaluation-report.md); [Phase 4 gate report](phase-4-gate-report.md) | Open in [backlog #115](https://github.com/avsngh-git/RAGpipeline/issues/115). |
| Synthesis abstains on partly answerable evidence | 57 of 131 synthesis calls set `insufficient_evidence`; a source review marked 0 of 69 reviewed contexts insufficient. | Generation | [ADR-0029](../adr/0029-claim-scope-words-and-prompt-trials.md) | Two prompt trials did not reduce abstention and were not adopted. |

The source-anchor counts are retrieval measurements on the v14 reviewed pool. The
planner counts come from a separate development pass. The abstention counts use stored
synthesis calls and reviewed contexts. They should not be compared as a single failure
rate.

## Retrieval failures

The v14 selected profile found 72 of 126 positive source anchors at rank 10 and 82 at
rank 50. Its source-anchor Recall@10 was 0.5714; retrieval quality varied by measure.
Dense gte paper nDCG@10 was 0.7183, above the selected hybrid profile's 0.6522, while
the selected profile's evidence nDCG@10 was 0.4074 versus 0.3610 for dense gte. The
report describes the selected profile's three closest quality gates as narrow passes
inside sampling noise. See the [v14 acceptance report](phase-2-acceptance-report.md).

Development results also show trade-offs. Hybrid E5 had higher source-anchor recall at
ranks 20 and 50 than dense E5 in the 19-family comparison, while dense E5 had higher
evidence nDCG@10 and lower warm latency. The paired top-10 source-recall delta for
hybrid E5 versus dense E5 was +0.012 with a 95% interval of [−0.071, +0.107], which
does not show a reliable top-10 gain. See the
[Phase 2 development report](../research/phase-2-development-report.md).

## Agent failures

### Planning and discovery

The Phase 3.5 natural pass did not choose `discover_papers` or `request_ingestion` in
any of its 10 runs. The report records 19 `search_papers` calls and 5
`search_evidence` calls. A separate forced-trigger pass tested ingestion behavior, so
its success does not show that the live planner would select those tools. The planner
diagnosis found the prompt frames discovery as conditional on local evidence being
insufficient. This remains backlog [#115](https://github.com/avsngh-git/RAGpipeline/issues/115).
See the [Phase 3.5 evaluation](phase-3.5-evaluation-report.md) and
[Phase 4 gate report](phase-4-gate-report.md).

### Timeouts and budgets

The recovered Phase 3 sweep completed 41 of 42 runs within budget; the remaining run
was categorized as a timeout. A separate fully sampled sweep completed 42 of 42.
Completed runs in both sweeps had no recorded budget violations. The timeout's exact
transport cause was not retained, so the report does not assign a root cause. See the
[Phase 3 evaluation](phase-3-evaluation-report.md).

### Trace-based diagnosis

The Phase 4 gate walkthroughs show how failures can be assigned to stages. Of the five
accepted walkthroughs, the report includes evidence-stage synthesis abstentions,
retrieval failures when discovery was unavailable, and verification rejections for
claims that failed quote checks. One discovery failure was caused by the API running
without an OpenAlex key; a rerun with discovery configured still showed the planner
choosing only local paper search. The owner rejected one earlier walkthrough and
accepted its replacement. See the [Phase 4 gate report](phase-4-gate-report.md).

`research-runs explain` reports stages such as planning, retrieval, evidence,
generation, verification, model, budget, ingestion, and infrastructure. The
`research-runs reproduce` command checks the stored configuration and may require the
run's recorded Git checkout. See the
[evaluation operations guide](../operations/evaluation.md).

## Answer failures

### Abstention and partial support

The fully sampled Phase 3 sweep had 1 answered, 9 partially supported, and 11
insufficient-evidence quick outcomes; deep research had 9 partially supported and 12
insufficient-evidence outcomes. On two explicitly unsupported deep tasks, one was
partially supported and one was marked insufficient evidence. These are
development-only observations, not answer-quality gates. See the
[Phase 3 evaluation](phase-3-evaluation-report.md).

In the later trace review, 57 of 131 synthesis calls declared insufficient evidence;
none of 69 reviewed contexts were labeled insufficient. Two prompt trials replayed on
21 development questions did not reduce abstention. The broader prompt kept more
claims but reduced reviewed supported-and-relevant precision; neither trial was
adopted. See [ADR-0029](../adr/0029-claim-scope-words-and-prompt-trials.md).

### Quote verification

The ADR-0025 review found that code quote checks rejected 7 of 15 partial or
unsupported claims and 2 of 60 supported claims. The latter two had non-verbatim
quotes. This is a measured trade-off: quote verification filters unsupported drafts
but can also reject supported claims. Later, claim scope words such as “both” and
“highest” were required to appear in the quote because a single table row cannot
support a broader comparison by itself. See [ADR-0025](../adr/0025-verified-quote-synthesis-with-thinking.md)
and [ADR-0029](../adr/0029-claim-scope-words-and-prompt-trials.md).

## Ingestion failures and safeguards

In the Phase 3.5 forced-trigger pass, 11 ingestion requests were refused with
`flagged_table_review_pending`. Extraction had flagged results tables for manual
review, and the existing finalization rule blocks publication until those tables are
reviewed. No child generation was published by that pass. This is a deliberate
quality safeguard that limits automatic ingestion of table-heavy papers. See the
[Phase 3.5 evaluation](phase-3.5-evaluation-report.md).

The same phase reports that a generation can signal configuration drift when evidence
average length changes by more than 10%; migration to a new configuration remains
manual. The report also identifies manual cleanup of retired or failed generations.
See the [Phase 3.5 evaluation](phase-3.5-evaluation-report.md) and
[source of truth, Phase 3.5 inputs](../agents/scientific-research-platform-source-of-truth.md).

## Failed and unreleased experiments

| Assessment or candidate | Result | What followed | Evidence |
| --- | --- | --- | --- |
| Phase 2 v3 | 10 of 14 gates passed; paper nDCG@10, evidence nDCG@10, reranker fallback, and warm p95 failed. | Kept failed under its frozen gates. Later comparisons returned to development data; the next assessment used a new frozen set. | [v3 report](phase-2-acceptance-report-v3.md) |
| Phase 2 v12 | 8 of 14 gates passed; six quality and source-recall gates failed. | The set was sealed. Work returned to development data; v13 was a separately frozen assessment. | [Acceptance report, v12](phase-2-acceptance-report.md) |
| Phase 2 v13 | 10 of 14 gates passed; paper nDCG@10 and three evidence ranking gates failed. | After the failure, ADR-0015 lowered three thresholds using development data only, and ADR-0016 raised the warm p95 limit for the fresh assessment. A new v14 set was then used once. | [Acceptance report, v13](phase-2-acceptance-report.md), [ADR-0015](../adr/0015-phase2-acceptance-gate-revision.md), [ADR-0016](../adr/0016-phase2-warm-latency-5000ms.md) |
| Two Phase 4 prompt trials | Neither trial reduced abstention; the broad prompt had lower reviewed supported-and-relevant precision than the current prompt. | Neither trial was adopted. | [ADR-0029](../adr/0029-claim-scope-words-and-prompt-trials.md) |
| Built-in Qdrant BM25 candidate | In a small 12-family comparison, metrics disagreed by task and had low evidence judgment coverage. | The comparison did not change the selected lexical approach. | [Lexical parity report](phase-3.5-lexical-parity-report.md) |
| Local follow-up candidates | Evidence-packing, displayed-evidence, and context-budget patches remained unmerged in the Phase 4 closeout. | They are candidates for owner review, not accepted product behavior. | [Source of truth, Phase 4 inputs](../agents/scientific-research-platform-source-of-truth.md) |

The later v14 held-out assessment passed its 16 gates, but the gate revision and narrow
margins remain part of that result. Dense gte ranked papers better than the selected
profile. See the [v14 acceptance report](phase-2-acceptance-report.md).

## Security and abuse findings

The `security-live` suite used 8 synthetic cases and fake retrieval, repeated 3 times.
Three of the seven cases with checks were marked as violations in each run. Review
found one actual code-control gap: the insufficient-evidence path exposed unverified
model text. That bug was filed as #139 and fixed. Two other flagged cases showed the
small model following injected text while the code controls held; the suite did not
yet distinguish model susceptibility from a breached control. See the
[Phase 4 security report](phase-4-security-live-report.md).

Scripted security and MCP attack suites passed CI. The Phase 5 gate records checks for
authentication scopes, rate limits, ownership, request limits, host and origin
validation, public text policy, and cursor tampering. See the
[Phase 4 gate report](phase-4-gate-report.md) and
[Phase 5 gate report](phase-5-gate-report.md).

## Open work

The Phase 4 handoff keeps answer quality, the `answered` definition, the planner,
flagged-table review policy, configuration-drift migration, the worker image, and a
dense-search tie-breaker in backlog [#115](https://github.com/avsngh-git/RAGpipeline/issues/115).
Phase 6 does not resolve that backlog. See the
[source of truth, Phase 4 inputs](../agents/scientific-research-platform-source-of-truth.md)
and [Phase 6 plan](../plans/phase-6-portfolio.md).
