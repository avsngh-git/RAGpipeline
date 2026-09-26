# Phase 2 — Evaluation protocol

Status: approved policy 2026-09-26; numerical settings and datasets not yet measured.
Read with the [roadmap](phase-2-retrieval-evaluation.md). This document owns scoring
and experiment rules; the roadmap owns execution order and completion status.

## Units and lineage

Use four distinct units:

- A **question family** is one information need, including its paraphrases and
  closely related variants. It belongs wholly to one split.
- A **paper judgment** rates a paper's relevance to that information need.
- A **source evidence judgment** identifies supporting source passages or table
  cells in a specific document version, independently of search chunk boundaries.
- An **evidence requirement group** describes pieces needed together, such as one
  result from each of two methods/papers. Equivalent supporting spans can be
  alternatives for one piece; retrieving duplicates does not satisfy other pieces.

Retain paper/document IDs, original-artifact checksum, extraction identity,
zero-based PDF page/region where known, canonical text offsets or table row/column
coordinates, and a short relevance rationale. For table evidence, identify header,
method, dataset, metric, value, units and footnotes when needed for interpretation.
Original PDF location is authoritative when parser output disagrees.

Chunk mappings reference these anchors. A new chunk configuration may require a
new mapping, but does not redefine relevance merely to favor its boundaries.
For a passage spanning blocks/pages, retain the constituent locations and offsets.
Missing coordinates are explicit; they are never invented.

## Judgment labels and review

| Label | Meaning | Example |
| --- | --- | --- |
| 0 | Irrelevant to the requested evidence | Mentions retrieval without evaluating the requested comparison |
| 1 | Useful context or incomplete support | Explains a method but omits the requested result |
| 2 | Direct support for a requested part | Reports the required comparison with identifiable conditions |

Labels measure relevance, not whether the result is favorable. A negative finding
can be direct evidence. Multiple documents may independently satisfy one requirement.
Paper and passage labels are separate: a relevant paper can contain irrelevant chunks.

All Phase 2 annotation/review is delegated to the assistant. Each record identifies
reviewer type, date, source checked, rationale and uncertainty. A second source-check
pass may reduce errors but is not an independent human validation. Never copy the
Phase 1 user-confirmation label onto new Phase 2 judgments.

The ten-question calibration establishes the labeling examples and source matching
rules. Revisit uncertain or high-impact labels against actual PDF pages, including
visual checks of table layout when needed. Preserve disagreement history. Unresolved
judgments are not gold; exclude them with a reason and disclose the resulting gap.

## Question sampling and splits

Cover all six agreed categories: discovery, specific evidence, table results,
cross-paper comparison, filters and missing evidence. Categories can overlap;
report denominators and intersections rather than summing them into a false total.
Use the corpus's actual coverage, including negative/mixed findings where present.
A question about a missing topic is an unsupported case, not a fabricated positive.

Start with ten calibration questions. Measure actual annotation/review effort,
then write the benchmark-size decision before constructing the full sets. That
decision must contain total families, development/held-out allocation, per-category
coverage, review pool depth, effort budget and rationale. Calibration families are
part of development only. No arbitrary fixed final size has been approved.

Use deterministic, versioned split assignment at the family level. Do not require
different paper corpora for each split: the agreed benchmark is retrieval over the
same fixed 100 papers. Split the information needs so paraphrases do not leak.
Record the snapshot/document manifest separately from the query split.

Pool bounded candidates from multiple retrievers/configurations, plus independently
source-found evidence. Preserve the pooling method and coverage; hide originating
system/rank during judgment where practical. Do not label a candidate relevant
because a model ranked it highly. Review benchmark source material locally under
the approved private-use policy; no hosted model is required for labeling.

Held-out judgments can be prepared before freeze, but held-out scores cannot guide
model/parameter selection. Frozen-run evaluation code must not insert gold positives
into candidates. In particular, check evaluator-library options that automatically
add positive documents: use only actually retrieved candidates for end-to-end scores.

## Match and deduplication rules

P2-05 must turn these policies into explicit, versioned executable rules:

1. Exact evidence IDs are sufficient only when the configuration is identical.
   Cross-chunk comparisons match canonical source anchors instead.
2. For prose, measure coverage of the annotated supporting span. Choose and freeze
   the required coverage rule during calibration. Incidental token overlap is not
   automatically direct support; a result missing the critical qualifier may be
   incomplete even if most tokens match.
3. For tables, require the annotated cell and its header/value associations and
   relevant context. The same number in another row or metric does not count.
4. Count each underlying judged evidence item once in ranking metrics. Additional
   overlapping hits yield no extra gain. Preserve rank positions occupied by redundant
   results so duplication is not rewarded by compressing the list during scoring.
5. A returned unit may support multiple requirement groups if it actually contains
   the required distinct evidence. Document how that mapping is credited, with
   synthetic examples that do not inflate nDCG by counting the same source twice.
6. Paper metrics count a paper once; evidence metrics retain distinctions between
   source evidence from different papers even when their wording is similar.

Do not leave these rules as manual interpretation after viewing held-out scores.

## Required metrics

| Metric | Definition and denominator |
| --- | --- |
| Paper nDCG@10 | Rank discounted graded paper relevance; gain 2^label - 1 |
| Evidence nDCG@10 | The same graded gain for uniquely credited source evidence; matching policy versioned |
| Direct MRR@10 | Reciprocal rank of first label-2 result in top ten; zero if absent |
| Judged Recall@20/@50 | Unique retrieved label-2 judgments divided by known label-2 judgments for that query and eligible filter scope |
| Evidence-group coverage | Fraction of required pieces retrieved; also report fraction of questions with every required piece present |
| Judgment coverage | Fraction of returned/evaluated candidates with resolved relevance judgments |
| Unsupported-query acceptance | Fraction of reviewed unsupported queries for which a configured relevance-acceptance policy accepts a hit |
| Failure/degradation rate | Failed or degraded requests divided by all attempted requests for each requested mode |
| Warm latency | Median and p95, sample counts and configuration for repeated warm requests |
| Cold cost/resources | Loading/build time, peak RAM/VRAM, batches and disk footprint reported separately |

Declare how a result matching multiple source judgments contributes to graded rank
gain before final scoring; cap each rank's gain at label 2 and use requirement-group
coverage to credit additional pieces. Hand-check ideal-ranking construction so the
normalization is achievable under that representation and nDCG stays within [0,1].

Unjudged is not a source-verified label 0. If using zero gain for unjudged results
in a pooled ranking calculation, label it a conservative judged-pool score and
report judgment coverage alongside it. Freeze this convention. Never describe
judged recall as recall over every relevant passage in the corpus. If unresolved
coverage materially prevents fair comparison, improve judgments without consulting
which system should win and rescore every configuration on the same benchmark version.

Queries with no eligible positive judgments have no defined positive-retrieval
recall/nDCG denominator. Report their counts and score them in the unsupported/empty
eligibility group; do not silently count them as perfect retrieval or dilute other
means with arbitrary zero values. MRR's answerable-query denominator is explicit.

A raw ranking without an acceptance cutoff has no calibrated supported/unsupported
decision. In that mode report returned-hit characteristics on unsupported questions,
not a fabricated rejection accuracy. If a cutoff is adopted, calibrate and freeze
it per profile, and report missed relevant results as well as false acceptance.

## Experiment matrix

Use staged experiments to control cost and interpretation. Freeze query sets,
judgments, filters and source corpus; vary only the stated factors.

| Stage | Compare | Hold fixed |
| --- | --- | --- |
| Hardware pilot | Candidate model load/inference on representative inputs | Input samples and measured resource procedure |
| Retrieval baseline | BM25; E5 dense; feasible BGE dense; their hybrid variants | Common compatible chunks, query set, eligible records and pool limits |
| Reranker comparison | Same fused pool untreated; MiniLM; feasible BGE reranker | Candidate identities, embedding/chunk settings and pair formatting policy |
| Chunking comparison | Section-aware vs fixed-window prose | Source documents/extraction, table handling, selected model and comparable budgets |
| Selection ablation | Grouping/diversity/candidate-limit settings | Model/corpus and development questions |
| Held-out assessment | Frozen named baselines and selected configuration | Final benchmark/configuration/acceptance identities |

A reranker cannot retrieve a missing candidate: report upstream candidate recall
and end-to-end metrics, not only reranking quality on supplied positive examples.
For input-length incompatibility, define a fair common evidence representation or
report the measured limitation. Model-specific hidden truncation is not a fair
embedding-only comparison.

At least two credible embedding candidates are required if hardware permits. The
shortlist is E5-small-v2 and BGE-base-en-v1.5. Reranker candidates are MS MARCO
MiniLM-L6-v2 and BGE-reranker-base. Candidate status is not a measured model choice.
Record failed feasibility runs rather than quietly omitting an unfavorable candidate.

Prefer a bounded, declared development grid. Candidate counts and score cutoffs
must not be tuned using test labels. Learned fine-tuning, generative query rewriting
and exhaustive hyperparameter searches are outside this agreed baseline.

## Timing and uncertainty

Benchmark interactive single-user operation on the recorded laptop. Separate cold
model/index loads, build cost and warm request timings. Record warm-up procedure,
number of repeats, query order/seed, CPU/GPU device, threads, batch size, versions,
concurrency and available memory. Repeat matched queries for comparable profiles.
Include filter, table and zero-match cases. Failed/timeout attempts remain counted.

Report paired per-question-family quality differences and uncertainty, for example
paired bootstrap intervals with recorded seed/repetitions. Resample families rather
than treating near-identical paraphrases as independent observations. Explain when
a small held-out sample only supports directional conclusions. Latency p95 estimates
also need their sample count; three timings are not a credible tail-latency study.

Numerical usefulness, latency and resource gates are set after development baselines,
then frozen before final assessment. No positive hybrid/reranker gain is required,
but useful quality and bounded operating behavior are. If no configuration meets the
gate, report a failed gate rather than redefine success using test results.

## Artifacts and replay

Each run manifest includes benchmark version/split hash, source snapshot/variant,
code revision, all model/index/chunk/analyzer/fusion/selection identities, hardware,
random seeds, query settings, declared comparisons, input limits, results and failures.
Store raw local records separately from sanitized reports and CI fixtures. Link them
by stable IDs/hashes so report claims can be traced without committing paper excerpts.

The repository currently broadly ignores JSON. Select explicitly permitted paths
for sanitized configuration/fixtures, or use tracked YAML/TOML where appropriate.
Do not disable exclusions globally or commit source PDFs/excerpts while fixing this.
Tiny synthetic benchmark fixtures run in CPU-only CI; real models and local corpora
run separately. Version the schemas and scorer, not just a Markdown results table.

Correcting a mistaken label requires a new benchmark version and a recorded reason.
Re-evaluate all compared systems on that version. Changes chosen after seeing test
scores are development of a new iteration; reserve new held-out families for a new
final claim and retain the earlier result history.
