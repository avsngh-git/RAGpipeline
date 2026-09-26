# Phase 2 — Retrieval and evaluation

Status: approved 2026-09-26; P2-01 and P2-02 complete; P2-03.1 inventory complete.

## Start and authority

Read the [source of truth](../agents/scientific-research-platform-source-of-truth.md)
in full. Its sections 9 and 21 define Phase 2; section 9.4 records this interview's
approved policy. Read the [handoff](phase-2-agent-handoff.md) for current progress.
[ADR-0008](../adr/0008-phase2-retrieval-evaluation-boundaries.md) records the
experiment and access boundaries. The [evaluation protocol](phase-2-evaluation-protocol.md)
defines judgments, metrics and experiment discipline.

The user delegated implementation, benchmark preparation, calibration and source
review to the agent. All new source judgments must identify their reviewer as
assistant, not human. Planning approval authorizes these decisions; this document
is a roadmap for the next implementation request, not a claim that tasks ran.

## Outcome

Deliver private local paper/evidence search over the accepted 100-paper corpus,
with lexical, dense, fused and reranked modes; filters; source-linked prose/table
results; stored one-hop citations; and a reproducible quality/latency comparison.
Choose a default using development evidence and validate it on held-out questions.
A simpler method may win. Useful quality and operational limits remain required.

Preserve the accepted snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`. Its
recorded 44,277 chunks are a baseline, not a required count for chunking variants.
Create separately identified experimental snapshots/indexes; share original PDFs
and extraction outputs. Ordinary search uses finalized snapshots only. Evaluation
may inspect explicitly named experimental drafts before their acceptance, through
an evaluation-only path that cannot become the API's default.

The phase excludes answer generation, LangGraph, MCP, public deployment, recursive
citation expansion, graph-based ranking and new corpus acquisitions. External
benchmarks are optional follow-up work, not an exit requirement. Existing project
obligations for later phases remain unchanged.

## How to execute a task

1. Select the first pending task whose prerequisites have completion evidence.
2. Read that task, its named reference material and affected implementation.
3. Implement its numbered substeps in order. Add meaningful behavioral tests with
   the change; each task's Done condition is mandatory.
4. Run focused checks, then the relevant shared checks. Record failures accurately.
5. Update the status table and handoff with revision/configuration identifiers,
   verification commands/results and the next unfinished substep.
6. Stop at a failed gate; repair it or report a concrete external blocker. Do not
   silently mark a partial result complete or redesign an approved requirement.

One substep is a reviewable unit, not necessarily one file or commit. Avoid creating
all modules as empty scaffolding. Build the smallest working path and extend it.
Keep progress explanations brief and educational. Routine implementation decisions
and review work are delegated; ask only when a material decision exceeds this scope.

## Roadmap and progress

P2-01 and P2-02 are complete. P2-03 is in progress after its reuse inventory. The table is the single implementation status checklist.
Tests and operational controls are added throughout, not postponed until P2-19.

| ID | Deliverable | Prerequisites | Status |
| --- | --- | --- | --- |
| P2-01 | Entry evidence and reproducible workspace | Approved plan | Complete |
| P2-02 | Search contracts, filter and access policy | P2-01 | Complete |
| P2-03 | Snapshot variants and retrieval configurations | P2-02 | In progress |
| P2-04 | Ten-question calibration and source judgments | P2-01, P2-02 | Pending |
| P2-05 | Deterministic evaluation harness | P2-03, P2-04 | Pending |
| P2-06 | BM25 lexical retrieval | P2-03 | Pending |
| P2-07 | Dense retrieval and embedding pilots | P2-03 | Pending |
| P2-08 | Fusion and consistent candidate filtering | P2-06, P2-07 | Pending |
| P2-09 | Paper, metadata and one-hop citation services | P2-08 | Pending |
| P2-10 | Cross-encoder reranking | P2-05, P2-08 | Pending |
| P2-11 | Evidence deduplication and bounded selection | P2-09, P2-10 | Pending |
| P2-12 | Development and held-out benchmark construction | P2-04, P2-05, P2-11 | Pending |
| P2-13 | Controlled prose-chunking alternative | P2-03, P2-07, P2-12 | Pending |
| P2-14 | Development experiments and acceptance limits | P2-05 through P2-13 | Pending |
| P2-15 | Default selection and experiment freeze | P2-14 | Pending |
| P2-16 | Typed paper/evidence HTTP API | P2-02, P2-09, P2-11, P2-15 | Pending |
| P2-17 | Failure, fallback and observability checks | P2-16 | Pending |
| P2-18 | Local runtime and rebuild runbooks | P2-16, P2-17 | Pending |
| P2-19 | Full verification and hosted CI | P2-18 | Pending |
| P2-20 | Held-out evaluation and phase acceptance | P2-12, P2-15, P2-19 | Pending |

Work sequence: foundations (01–05), search services (06–11), evaluation and
selection (12–15), then API/runtime/acceptance (16–20). A thin API smoke route may
be wired earlier to test transport boundaries, but P2-16 completes only after the
selected configuration is frozen. No task requires speculative later-phase code.

## P2-01 — Establish entry evidence

**Inputs:** Phase 1 audit/closeout, current Git revision, hosted CI, accepted snapshot.

1. **01.1 Verify the revision.** Record HEAD and worktree changes. The last observed
   remediation CI passed on `d28e1adc299d6199774c78a2d63cb3eb0870d5ab`, run
   [36238052340](https://github.com/avsngh-git/RAGpipeline/actions/runs/36238052340).
   Recheck if source changed. Distinguish recorded checks from checks rerun now.
2. **01.2 Verify document availability.** Check required specification, ADR, plan
   and handoff files are not ignored and are included in the eventual change set.
   The planning change removes the residual bare `docs` ignore rule. Eligibility
   is not a commit: verify tracked contents before claiming fresh-checkout readiness.
3. **01.3 Inspect the database target and schema.** The accepted corpus resides in
   `research_phase1_review`, not `research`. Compare applied migrations with the
   repository, including 013/014. If a migration is needed, record a backup/restore
   procedure and use the migration runner explicitly; preserve accepted membership
   and legacy chunk selection. Do not treat a validation command's implicit schema
   writes as a read-only audit.
4. **01.4 Verify baseline integrity.** Read-only snapshot validation, source checksum
   checks and snapshot-scoped PostgreSQL/Qdrant identity reconciliation must pass.
   The shared Qdrant collection also contains the retained ten-paper draft: never
   infer accepted membership from collection-wide counts.
5. **01.5 Record resources.** Measure current CPU/RAM, GPU/VRAM, physical host disk
   availability and service usage. Establish bounded directories for new lexical
   indexes, model caches and experiment outputs, excluded from Git.

**Done:** write `docs/reviews/phase-2-entry-check.md` with actual revision, schema,
CI, corpus and hardware observations; resolve failed prerequisites before model runs.
Use synthetic fixtures and isolated services for tests, not accepted corpus writes.

**Completed 2026-09-26:** see the [entry check](../reviews/phase-2-entry-check.md).
Migrations 013/014 are applied to the accepted review database; the finalized
snapshot, source checksums and snapshot-scoped Qdrant identities pass read-only checks.

## P2-02 — Define contracts, filters and access

**Inputs:** source section 9, approved query categories and private-local policy.

1. **02.1 Define typed requests.** Require query, snapshot ID and retrieval profile;
   define defaults for bounded result count and optional filters. Reject blank or
   oversized queries, unknown fields/modes, invalid IDs and invalid ranges.
2. **02.2 Define result types.** PaperHit and EvidenceHit retain stable IDs,
   document/extraction/chunk versions, source locators, ranks and component scores.
   Responses include effective configuration, requested/effective mode, warnings,
   truncation indicators and request ID. Scores are not probabilities.
3. **02.3 Define filters.** Support inclusive year bounds, selected paper IDs,
   evidence kind and document version kind. AND different fields; OR allowed values
   within a field. Missing metadata fails a filter requiring that value. Reject
   unsupported evidence filters on metadata-only operations rather than ignore them.
4. **02.4 Define service access.** An explicit trusted private-local execution profile
   may inspect retained, storage/index-permitted evidence. Public passage permissions
   remain false. Enforce profile and source permissions in reusable services; a
   client-supplied boolean or spoofable address header cannot grant private access.
   Metadata-only routes must not leak passages through summaries/debug fields.
5. **02.5 Pin bounds.** Select conservative local defaults for query length, result
   count, candidate pool, per-paper evidence and request timeout; serialize them in
   configuration and test their boundaries. Performance targets remain provisional
   until the pilot. Document endpoint applicability and error categories.

**Done:** typed contracts plus a field/behavior table in
`docs/api/phase-2-search-contract.md`; validation/filter/permission tests pass.
Use plain services behind HTTP adapters. Runtime framework types stay at boundaries.

**Completed 2026-09-26:** HTTP and framework-independent request/result contracts,
filter semantics, server-owned access policy and provisional bounds are implemented.
The metadata-only response has no evidence-text field. See the [search contract](../api/phase-2-search-contract.md).
Focused checks and the non-integration repository suite pass; see the current
[agent handoff](phase-2-agent-handoff.md) for exact commands and results.

## P2-03 — Version experimental snapshots and retrieval profiles

**03.1 inventory complete 2026-09-26:** existing snapshots freeze member selection;
`SnapshotRepository` selects per-member extraction and chunk configuration; migrations
013/014 provide resumable job plans and per-member chunk-set identity. `IndexConfiguration`
is a canonical identity stored alongside per-snapshot index build state, with exact
Qdrant reconciliation; `E5SmallV2Embedder` is already behind `VectorEmbedder`. The
existing stage configuration/repository and `PdfEvidenceProcessor` persist resumable
extraction/chunk outputs. No schema extension is justified by this inventory alone.
Proceed to **03.2** and define the profile identity over these existing seams.

**Inputs:** snapshot/index/chunk persistence from Phase 1, new contracts.

1. **03.1 Inventory reuse.** Read SnapshotRepository, IndexRepository,
   IndexConfiguration, the embedding adapter, migrations 013/014 and extraction/
   chunk checkpoints before adding storage. Retain their existing stable identities.
2. **03.2 Define the retrieval profile.** Include snapshot/chunk selection, lexical
   analyzer/index identity, embedding revision/preprocessing/dimensions, reranker
   revision/preprocessing, fusion settings, candidate limits and selection rules.
   Compute canonical identities without secrets. Keep Git revision as provenance,
   separate from component compatibility identities.
3. **03.3 Define variant lineage.** Every variant references the accepted paper and
   document selection and identifies its extraction/chunk/model differences. Source
   PDFs and unchanged extraction results are shared. Record a schema ADR and add a
   new migration only where existing representations are insufficient.
4. **03.4 Make publication atomic.** Build derived indexes under temporary/versioned
   identities, verify IDs/counts/configuration, then mark ready. Interrupted builds
   are resumable/rebuildable and cannot become serving defaults. Protect active
   references from cleanup; serialize conflicting builds/publication operations.
5. **03.5 Enforce boundaries.** Resolve snapshot/profile once per request. Validate
   the intended lexical and dense index before retrieval and reject incompatible
   combinations. Finalized serving profiles stay fixed; changed evidence/configuration
   gets a new variant. Evaluation drafts require explicit separate access.

**Done:** a synthetic pair of variants shares sources but never mixes evidence or
model vectors; interrupted builds cannot be served; rebuild and retention tests pass.

## P2-04 — Calibrate ten questions with delegated source review

**Inputs:** accepted papers/PDFs, evaluation protocol, private-local source access.

1. **04.1 Draft ten question families.** Cover paper discovery, specific evidence,
   table results, cross-paper comparison, filters and missing evidence. Include
   negative/mixed findings where actually present. Record the coverage matrix.
2. **04.2 Inspect independent sources.** Check relevant PDF pages against extracted
   prose/tables. Record source checksums, locators, expected evidence and rationale.
   A parser output or another model's score alone does not establish a label.
3. **04.3 Label relevance.** Apply 0/1/2 judgments from the protocol, keeping paper
   relevance separate from evidence relevance. For comparisons, list required
   evidence pieces. For tables, check values with row/column meaning and context.
4. **04.4 Record reviewer limitations.** Label every new judgment assistant-reviewed.
   Independently revisit ambiguous cases using the source; retain uncertainty and
   exclude unresolved items from gold scoring with explicit reasons. Do not invent
   a second human reviewer or portray model agreement as human validation.
5. **04.5 Measure effort.** Record review time and candidate counts. Then select and
   document development/test sizes, per-category coverage, candidate-pool review
   depth and a review-time budget. Explain whether the resulting test set supports
   only directional conclusions. No fixed large benchmark size was approved in advance.

**Done:** ten traceable calibration questions and a written labeling/workload decision
in `docs/reference/phase-2-calibration.md`. These ten remain development material.
Private excerpts stay in ignored local-reference storage; sanitized rules are versioned.

## P2-05 — Build deterministic evaluation primitives

**Inputs:** calibration schema and [evaluation protocol](phase-2-evaluation-protocol.md).

1. **05.1 Define loaders.** Validate query families, filters, split, judgments,
   source anchors and reviewer status. Reject duplicate IDs, invalid cross-references,
   overlapping family splits and malformed/empty expected evidence groups.
2. **05.2 Implement source matching.** Map returned chunks to canonical source
   passages/table cells, including chunks spanning multiple original text blocks.
   Freeze explicit overlap/coverage rules. A number occurring elsewhere in a table
   is not a match. Match table cell associations and needed header/unit context.
3. **05.3 Implement scoring.** nDCG@10, direct-evidence MRR@10, judged Recall@20/50,
   comparison-group coverage, judgment coverage and unsupported-query measures.
   Score paper and evidence results separately; deduplicate the same source evidence.
4. **05.4 Define run records.** Persist query/run IDs, dataset/split version, code and
   effective configuration IDs, returned IDs/ranks/component scores, timing, failure
   categories and hardware. Keep private query/excerpt data in controlled local
   artifacts; sanitized reports contain only permitted examples and aggregates.
5. **05.5 Test hand-calculated examples.** Include ties, no positives, duplicate
   chunks, partial table coverage, repeated papers, unjudged hits, failed requests
   and equivalent evidence represented by different chunk boundaries.

**Done:** deterministic expected scores on tiny synthetic examples, reproducible
run serialization, and a small evaluation command over fake search services. No model
or network download is required for these tests.

## P2-06 — Implement BM25 lexical search

**Inputs:** ready variant manifest, canonical evidence, lexical candidate BM25S.

1. **06.1 Pilot the dependency.** Verify current BM25S release/API/license and pin an
   evaluated version. Measure build/query memory and latency on the actual chunk
   count. Confirm ability to restrict eligible documents before top-k. If it fails,
   document the blocker and propose an alternative; do not silently add a service.
2. **06.2 Define analyzers.** Version tokenization, normalization, stemming/stopword
   choices and numeric/acronym handling. Preserve scientifically meaningful terms,
   punctuation cases and table numbers in source text even if analyzed differently.
3. **06.3 Build indexes.** Create an evidence index and a separate paper title/abstract
   representation where available. Bind index row positions to stable authoritative
   IDs and checksums; account for empty/missing fields and duplicate source records.
4. **06.4 Filter correctly.** Resolve eligible IDs from authoritative metadata and
   score/select within that set. Retrieving global top-k and then discarding filtered
   hits is insufficient. Handle zero eligible IDs and zero term matches explicitly.
5. **06.5 Save/reload/rebuild.** Serialize only trusted local index artifacts, validate
   compatibility on load, publish completed builds atomically and report storage use.
   Provide a CLI smoke query through the same search service the API will use.

**Done:** lexical scores/order match a small independent example; rare terms,
acronyms, numbers, empty matches, restrictive filters, save/load and rebuild pass.
Record measured BM25S acceptance and pinned analyzer choices in an implementation ADR.

## P2-07 — Implement dense search and embedding feasibility

**Inputs:** existing E5 adapter/Qdrant service, two candidate model cards.

1. **07.1 Reuse the baseline.** Implement query embedding and authoritative evidence
   hydration for E5-small-v2. Preserve its query/passage prefixes and pinned revision.
   Validate dimensions, normalization and snapshot/index configuration before querying.
2. **07.2 Pilot BGE-base-en-v1.5.** Verify model license, immutable revision, tokenizer,
   query instructions and input limits. Start with small batches and representative
   prose/tables; measure peak RAM/VRAM and CPU/GPU latency before full indexing.
3. **07.3 Preserve input meaning.** Use the same source chunk set for embedding-only
   comparisons. Check token counts under both tokenizers. If inputs cannot fit, define
   a common compatible experimental chunk set and rerun both candidates on it;
   never silently truncate cells or compare undisclosed different evidence.
4. **07.4 Build separate compatible indexes.** Record embedding configuration and
   readiness, reconcile exact IDs/payloads, then test reload/rebuild. Do not overwrite
   the accepted E5 collection. Document a measured feasibility failure if the second
   candidate cannot run locally; only hardware evidence can justify the spec exception.
5. **07.5 Apply filters before top-k.** Add supported metadata predicates to dense
   retrieval, backfill/rebuild required payloads safely, and verify authoritative
   eligibility again when hydrating. Deleted/stale/wrong-snapshot references are
   integrity errors, not silently returned text.

**Done:** both feasible adapters retrieve synthetic known neighbors and obey the
same filter truth table; real-model pilot measurements and index identities recorded.
A deterministic adapter substitute supports CI.

## P2-08 — Fuse candidate lists

**Inputs:** tested lexical/dense services and common filter contract.

1. **08.1 Implement reciprocal rank fusion.** Use 1-based ranks and a versioned
   positive rank constant; sum rank contributions for matching evidence IDs. Treat
   the common constant 60 as a development starting value, not an approved winner.
2. **08.2 Define deterministic ordering.** Resolve ties with stable IDs; a missing
   result contributes no rank term. Preserve original lexical/dense ranks and scores.
3. **08.3 Bound pools.** Cap each retriever and the fused union. Record actual counts,
   applied filters and truncation. Both branches must use the same snapshot/profile.
4. **08.4 Exercise restrictive filters.** Verify each branch can find eligible matches
   below the global unfiltered top-k; verify empty eligibility and missing metadata.
5. **08.5 Handle failures explicitly.** Default to structured failure if a requested
   branch fails. Implement only named, explicitly enabled degraded paths and record
   effective mode. Do not present lexical-only results as successful hybrid output.

**Done:** hand-computed RRF cases, duplicate IDs, ties, disjoint lists, all filter
combinations and one-branch failure tests pass with component provenance preserved.

## P2-09 — Paper search, metadata and citations

**Inputs:** filtered evidence retrieval, metadata lexical representation, local graph.

1. **09.1 Implement paper reads.** Resolve public paper IDs consistently, return actual
   document version and metadata availability, and distinguish unknown IDs from
   records outside the requested snapshot. Use bounded service-layer queries.
2. **09.2 Group evidence into papers.** Use the strongest eligible evidence hit as
   the initial paper evidence score. Retain up to three distinct supporting hits;
   summing all chunk scores is not the baseline.
3. **09.3 Combine metadata and evidence candidates.** Keep title/abstract ranking and
   evidence-derived ranking separate, then use a documented rank-based fusion rule
   as the initial aggregation. Do not add incomparable raw scores. Metadata-only
   matches have no fabricated supporting passage. Evaluate this rule in P2-14.
4. **09.4 Define diversity.** Paper search returns one record per paper. Candidate
   caps must bound scanning and expose result truncation rather than claim exhaustive
   total relevance. Evidence-search per-paper caps are implemented in P2-11.
5. **09.5 Expose one-hop graph reads.** References/citations come only from stored
   real links. Return resolved metadata and explicitly marked unresolved external
   IDs, without fabricated titles. Mark records outside the selected corpus as such;
   never attach their full text. Paginate and state that incoming edges cover the
   locally observed graph, not all global citations.

**Done:** known-title, evidence-only and metadata-only matching cases; long-paper
bias fixture; missing records; reference/citation direction; pagination; unresolved
and out-of-snapshot endpoint tests pass. No live OpenAlex call occurs on search.

## P2-10 — Cross-encoder reranking

**Inputs:** fixed pilot candidate lists, initially from the existing E5 hybrid path.
Final embedding/reranker selection happens in P2-14/15.

1. **10.1 Pilot both candidates.** Evaluate MS MARCO MiniLM-L6-v2 and BGE-reranker-base
   on bounded representative query/prose/table pairs. Record revisions, licenses,
   preprocessing, maximum pair length and CPU/GPU memory and latency.
2. **10.2 Define pair construction.** Version query and evidence formatting, preserving
   table associations. Include only documented title/section context. Account for
   query tokens in the pair budget; use explicit source-linked windows or a recorded
   length policy, not silent removal of the relevant result cell.
3. **10.3 Implement the adapter.** Batch off the event loop; enforce inference timeout,
   finite output scores, input/output alignment, stable ties and candidate-count limits.
   Return raw ranking scores without interpreting them as calibrated probabilities.
4. **10.4 Preserve retrieval provenance.** Rerank only the supplied candidate pool;
   retain all earlier component scores/ranks. Do not inject known relevant evidence
   into the candidate list during end-to-end evaluation.
5. **10.5 Exercise failure paths.** Missing weights, device exhaustion, invalid scores,
   timeout and partial batches must produce controlled outcomes. Explicit fallback
   uses the unchanged fused ranking and identifies the failed reranker.

**Done:** model-fake tests verify alignment, limits and errors; feasible real-model
runs have measured resource profiles. If a candidate fails feasibility, retain the
result and rationale rather than silently replace it with an unapproved larger model.

## P2-11 — Select evidence without losing meaning

**Inputs:** ranked candidates, source anchors and table structures.

1. **11.1 Deduplicate by evidence identity and source overlap.** Remove exact duplicate
   hits; define conservative same-document overlap rules. Similar wording in different
   papers is not automatically duplicate evidence.
2. **11.2 Bound per-paper results.** Make the cap configurable. Choose development
   starting defaults, then measure relevance/diversity tradeoffs in P2-14.
3. **11.3 Preserve table context.** Return selected rows/cells with needed headers,
   caption, units, footnotes and source references. Include structured fields plus a
   bounded readable representation; never flatten a value away from its meaning.
4. **11.4 Enforce result/context budgets.** Bound item count and returned text/tokens.
   Prefer whole evidence units that fit, or explicitly source-linked subdivisions.
   Report omissions/truncation. Do not clip a table mid-cell or silently remove units.
5. **11.5 Expose weak-match semantics.** Empty eligibility has a distinct reason.
   Ranked candidates imply neither answerability nor verified claim support. A
   relevance cutoff remains disabled until calibrated for that exact mode/profile.

**Done:** overlapping prose, repeated table headers, distinct cross-paper evidence,
oversized units and budget exhaustion have deterministic, source-resolvable results.

## P2-12 — Construct the larger benchmark

**Inputs:** calibration findings, working retrieval variants, evaluation protocol.

1. **12.1 Freeze the sampling plan.** Apply the post-calibration workload decision;
   include all six categories in development and held-out coverage where meaningful.
   Keep paraphrase families together and the ten calibration questions out of test.
2. **12.2 Prepare pooled candidates.** Combine bounded results from lexical, dense
   and feasible alternative configurations plus independently source-found evidence.
   Mask system/rank origins during relevance review when practical. Record pool
   depth, source selection method and observed selection biases.
3. **12.3 Review sources under delegation.** Apply the calibrated labels and matching
   rules. Include numeric/table and negative/mixed-result cases. Mark uncertainty and
   incomplete judgments explicitly; unsupported means no evidence found under the
   documented review procedure, not proof of absence from scientific literature.
4. **12.4 Separate development and test access.** Store split manifests and content
   hashes. The tuning workflow reads only development scores. Preparing held-out
   judgments is permitted; using their scores to choose parameters is not.
5. **12.5 Audit judgment quality.** Recheck ambiguous/high-impact labels from PDFs,
   record disagreements/corrections and coverage of candidate pools. Assistant-only
   review remains a disclosed limitation, even with a second automated review pass.

**Done:** immutable initial benchmark version, split/family checks, review coverage,
source mappings and sanitized dataset card. No unresolved label is disguised as gold.

## P2-13 — Add the controlled chunking baseline

**Inputs:** source-based judgments, retained extraction, variant lifecycle.

1. **13.1 Define fixed-window prose chunking.** Keep the same normalized prose and
   source coverage; form fixed token windows with overlap across section boundaries.
   Version size, overlap, tokenizer and reading-order rules. Start with a comparable
   token budget to the existing approach; exact settings are pilot decisions.
2. **13.2 Preserve locators.** Store mappings for every constituent source span where
   a window crosses a block/page/section. Do not pretend a cross-page chunk has one
   precise bounding box. Keep original text and missing-location information honest.
3. **13.3 Keep tables constant.** Reuse table units, reviewed corrections and source
   exclusions. The initial experiment varies prose boundaries, not table extraction.
4. **13.4 Reuse extraction.** Exercise Phase 1 extraction/chunk compatibility checkpoints;
   verify no parser call for unchanged extraction. Create a new chunk/variant identity
   and corresponding lexical/vector indexes with measured storage use.
5. **13.5 Check fairness.** Map both chunk sets to identical source judgments and
   verify required evidence can be represented under both model tokenizers. Match
   model/reranker/settings when measuring chunking effects.

**Done:** variant lineage, reprocessing test, source coverage/mapping tests and a
paired development evaluation. Accepted snapshot and extraction remain unchanged.

## P2-14 — Run development experiments

**Inputs:** development benchmark and the [experiment matrix](phase-2-evaluation-protocol.md#experiment-matrix).

1. **14.1 Validate the harness end to end.** Run a tiny subset and manually reconcile
   saved IDs/scores/source matches before spending time on full comparisons.
2. **14.2 Compare embeddings and retrieval.** On a common chunk set, run lexical-only,
   both feasible dense models and their hybrid configurations. Keep candidate limits
   and query/permission/filter behavior controlled. Record failure rates and limits.
3. **14.3 Compare rerankers.** Use identical saved hybrid pools for both candidates;
   compare the original ordering with each reranked ordering. Report candidate recall
   separately so a reranker cannot conceal missing evidence from stage one.
4. **14.4 Compare chunking and selection.** Compare section-aware vs fixed windows
   using the selected development model; assess paper aggregation, duplicate removal
   and per-paper caps with a bounded list of settings, not an unbounded grid search.
5. **14.5 Measure runtime.** Record cold model/index loading separately from repeated
   warm requests, medians/p95, sample counts, inference batches, RAM/VRAM and disk.
   Include prose/table queries and zero-match/filter cases. Control concurrency.
6. **14.6 Set explicit acceptance limits.** From baseline measurements and source
   judgments, record useful-quality floors, maximum failure rate, latency/resource
   limits and allowed regression margins before held-out evaluation. Explain their
   practical meaning; observed weak performance is not itself an acceptable target.
   Under delegation the agent records the decision without inventing user approval.

**Done:** reproducible development comparison, failures and rationale in
`docs/reference/phase-2-development-report.md`, plus a versioned numeric acceptance
configuration. If usefulness remains inadequate, improve using development data.

## P2-15 — Freeze the selected configuration

**Inputs:** development report and feasibility/quality gates.

1. **15.1 Choose the default.** Select the simplest feasible configuration meeting
   the declared useful-quality and runtime limits. A small uncertain gain does not
   automatically justify a slower model. All required methods remain available for
   comparison even if lexical-only or dense-only becomes the default.
2. **15.2 Decide unsupported-query handling.** Calibrate any optional score cutoff
   only for the chosen mode/profile; freeze it with labeled supported/unsupported
   development cases. If unreliable, leave it disabled and report ranking-only
   behavior and the limitation; do not claim automatic answerability detection.
3. **15.3 Freeze the manifest.** Record model/index/chunk/analyzer/fusion/selection/
   threshold versions, candidate counts, benchmark matching rules and acceptance
   configuration. Finalize/validate the serving variant through the lifecycle gate.
4. **15.4 Define held-out comparisons.** Freeze a bounded named set: lexical baseline,
   selected dense, corresponding hybrid, hybrid with selected reranker, and the
   paired chunking comparison. Declare any additional comparison before results.
5. **15.5 Verify replay.** Reload the saved profile and run development smoke queries
   without hidden notebook state. Reconcile every referenced index and source.

**Done:** a signed-by-reviewer decision record/configuration hash ready for held-out
execution. Assistant reviewer identity is explicit; no cryptographic signing is required.

## P2-16 — Expose the HTTP contracts

**Inputs:** tested services and frozen default profile.

1. **16.1 Implement POST /v1/search.** Return bounded distinct papers and supporting
   matches, metadata/evidence score provenance and applicable filters.
2. **16.2 Implement POST /v1/evidence/search.** Return authorized source-linked prose/
   tables, selection/truncation details and requested/effective retrieval modes.
3. **16.3 Implement GET /v1/papers/{paper_id}.** Document an unambiguous route-safe
   representation for stored paper IDs, resolve it consistently and return metadata,
   selected document version and availability without leaking restricted passages.
4. **16.4 Implement GET references/citations routes.** Use the existing specified
   /v1/papers/{paper_id}/references and /citations paths, bounded pagination and
   explicit unresolved/out-of-corpus records. Keep network discovery outside requests.
5. **16.5 Map failures.** Distinguish validation, unknown resource, draft/incompatible
   profile, permission denial, dependency unavailable and timeout. Stable error codes
   and request IDs survive transport mapping; raw SQL/model/credential details do not.
6. **16.6 Document OpenAPI examples.** Include prose/table search, missing metadata,
   no eligible records, requested fallback and unresolved citations using synthetic
   or otherwise display-permitted data.

**Done:** API tests prove transport validation, each endpoint's happy/error paths,
source permissions and response schemas. Routes delegate to reusable services; they
contain no raw database queries or ranking logic. /health and /ready keep working.

## P2-17 — Verify failures, fallbacks and observability

**Inputs:** HTTP/service path, deterministic failure injection.

1. **17.1 Implement named fallbacks.** Strict is default. Explicit policies may permit
   hybrid-to-lexical or reranked-to-fused fallback. Policy validation rejects impossible
   paths; profile/permission/integrity failures never trigger a less-restricted path.
2. **17.2 Bound execution.** Enforce per-component and total deadlines, bounded model
   concurrency, cancellation cleanup and retryable-I/O limits. A timeout does not
   leave unbounded model tasks consuming the GPU after the request is gone.
3. **17.3 Record service measurements.** Correlate requests with snapshot/config IDs,
   component durations/counts, filter counts, effective mode and failure categories.
   Keep raw queries and source passages out of default logs. Experiment artifacts
   may retain controlled local inputs for reproducibility.
4. **17.4 Test injected faults.** Missing lexical index, unavailable Qdrant/PostgreSQL,
   model timeout/OOM, invalid model output, stale IDs and incompatible profile must
   have explicit outcomes. Verify failures and fallbacks remain distinct in metrics.
5. **17.5 Validate readiness.** Define required components for the selected profile;
   unavailable required models/indexes make that profile unready. Optional profiles
   must not falsely break unrelated readiness or silently replace the default.

**Done:** fault-injection and secret/source-safe logging tests pass; one failed
search can be explained from IDs, timings and classified errors without private text.
Full Langfuse/agent tracing remains later-phase work.

## P2-18 — Package local operation and rebuild

**Inputs:** selected profile, persistent sources, current Compose/dependency setup.

1. **18.1 Provide executable operations.** Document actual implemented commands for
   index build/status/validate/rebuild, evaluation, source inspection and benchmark
   reports. Commands use shared services; avoid separate notebook implementations.
2. **18.2 Define local profiles.** Provide the deterministic small test profile and
   real-model local profile with CPU operation and optional GPU acceleration. Keep
   localhost bindings and trusted private-local access policy explicit. Mount caches
   and indexes; exclude weights, source PDFs and secrets from images/build context.
3. **18.3 Reconcile dependencies.** Keep pyproject, Conda specification, applicable
   lock files and optional-model instructions consistent. Pin evaluated model/library
   revisions. CI installation must not fetch large models implicitly.
4. **18.4 Demonstrate rebuild.** Build a derived index under a new isolated identity
   from retained data, validate exact references/configuration, and compare smoke
   query behavior. Delete only disposable audit artifacts, never accepted indexes.
5. **18.5 Write runbooks.** Cover startup, database/snapshot selection, first-model
   loading, config changes, broken-index repair, permission failures, disk limits,
   controlled cleanup and evaluation replay in `docs/operations/phase-2-search.md`.

**Done:** documented commands work from a clean environment with small fixtures;
local model procedure is demonstrated separately. No private knowledge is needed to
identify which database, snapshot and profile serve a request.

## P2-19 — Verify the integrated implementation

**Inputs:** all preceding code, frozen evaluation configuration, isolated services.

1. **19.1 Run the small suite.** Ruff, formatting, strict mypy, deterministic unit/API/
   evaluation tests and isolated PostgreSQL/Qdrant integration tests all pass.
2. **19.2 Check migration/compatibility.** Verify clean-database and Phase 1 upgrade
   paths, rollback on failed migration, retained accepted snapshot and index rebuild.
3. **19.3 Exercise security/correctness boundaries.** Filter equivalence, draft/config
   isolation, no text for unauthorized contexts, bounded malicious/oversized inputs,
   safe errors, source-aware deduplication and no-result behavior have regression tests.
4. **19.4 Check packaging.** Dependency consistency/audit and Docker build pass;
   expensive GPU evaluations remain separate from ordinary CI.
5. **19.5 Verify hosted CI.** Record a successful run for the actual implementation
   revision. Follow the user's commit/push workflow; if the revision is not published,
   report local success and hosted CI pending rather than claim the phase complete.

**Done:** actual command results, revision and CI link in a completion checklist.
Passing tests are necessary but do not replace the held-out quality gate.

## P2-20 — Held-out evaluation and final acceptance

**Inputs:** frozen benchmark/profile/acceptance configuration and passing implementation.

1. **20.1 Verify freeze identities.** Check the code/configuration/dataset hashes and
   no family leakage. Keep held-out labels out of the retrieval/runtime inputs.
2. **20.2 Execute the declared comparisons.** Save per-query results, source matches,
   failures, effective modes and repeated timing measurements. Exclude degraded runs
   from successful execution counts for the requested method; report them separately.
3. **20.3 Apply the predeclared gates.** Compare quality, coverage, usefulness and
   runtime against frozen limits. Report paired differences and uncertainty. If a
   gate fails, mark it failed; test-driven tuning requires a new honest assessment
   with new held-out questions, not reusing this test as an unseen benchmark.
4. **20.4 Produce the acceptance report.** Include corpus/benchmark/model/index/code
   identities, query/category counts, labeling effort/uncertainty, judgment coverage,
   all metrics, failures, latency/RAM/VRAM/storage, selected default, ablations,
   permissions, reproducible commands and limitations. Use
   `docs/reference/phase-2-acceptance-report.md`.
5. **20.5 Update guidance and handoff.** Update the source of truth, plan status,
   README and handoff with actual results, CI, serving profile and Phase 3 inputs.
   Record final embedding/reranker/lexical choices in ADRs when accepted.

**Done:** all required tasks have evidence, the frozen held-out gate passes, the
private local API and rebuild workflow work, and a new contributor can reproduce
small tests and understand the real-model results. External benchmark performance,
answer synthesis and general scientific coverage are not claimed.

## Shared verification commands

Run from the repository with the project Conda environment active. These are
existing checks; new search/evaluation command names must be documented when built.

```bash
conda activate sci_research_agent
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest -m 'not integration'
python -m pip check
```

For live tests, start fresh disposable services. The current test fixture requires
an isolated database named `research_test`. Set RESEARCH_PLATFORM_TEST_DATABASE_URL
and RESEARCH_PLATFORM_TEST_QDRANT_URL to those services, then run
`python -m pytest -m integration`. Never point test variables at `research` or
`research_phase1_review`. Reuse the CI workflow's migration/audit/build commands.
Do not count skipped integration tests as a live pass.

## Decision timing and stop conditions

| Decision | Responsible task | Rule |
| --- | --- | --- |
| BM25S version/analyzer/filter implementation | P2-06 | Pilot and ADR before treating dependency as accepted |
| Source-match rules and review workload | P2-04/05 | Calibrate, record and freeze before final scoring |
| Model revisions, fit and input budgets | P2-07/10 | Measure locally; never infer feasibility from a model name |
| Development/test size and split | P2-04/12 | Select after ten-question review; document coverage/uncertainty |
| Chunk/window sizes and overlap | P2-13 | Versioned development choices preserving source meaning |
| Ranking pools, fusion/diversity settings | P2-08/11/14 | Bound and compare on development questions |
| Quality/latency thresholds and default | P2-14/15 | Freeze before held-out evaluation |
| Permanent schema changes | P2-03 or first consumer | ADR and new migration; preserve existing evidence |

Escalate a genuine change to the locked corpus, public-access policy, paid compute,
excluded infrastructure or scientific acceptance contract. Routine source reviews,
implementation choices within this plan and development measurements are delegated.
The original frozen snapshot is retained even if a variant wins.

## Primary implementation references

Verify current APIs and pin evaluated revisions at implementation time:
[BM25S](https://github.com/xhluca/bm25s),
[BGE-base-en-v1.5](https://huggingface.co/BAAI/bge-base-en-v1.5),
[MiniLM reranker](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2),
[BGE reranker](https://huggingface.co/BAAI/bge-reranker-base),
[Sentence Transformers retrieve/rerank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html),
[reranking evaluation](https://www.sbert.net/docs/package_reference/cross_encoder/evaluation.html).
These are implementation references, not evidence that a candidate wins here.
