# Phase 2 — Retrieval and evaluation

Status: approved 2026-09-26; current status assistant-reviewed 2026-09-28. The earlier v3 assessment failed four frozen gates and v11 passed historically. The fresh R8 v12 assessment completed with 8/14 gates passing: warm p95 passed at 894.3 ms against the approved 2,000 ms limit, while six paper/evidence quality and source-coverage gates failed. Phase 2 remains open; the v12 set is sealed. See the [current acceptance report](../reference/phase-2-acceptance-report.md) for gate values and next steps.

## Start and authority

Read the [source of truth](../agents/scientific-research-platform-source-of-truth.md)
in full. Its sections 9 and 21 define Phase 2; section 9.4 records this interview's
approved policy. Read the [handoff](phase-2-agent-handoff.md) for current progress.
[ADR-0008](../adr/0008-phase2-retrieval-evaluation-boundaries.md) records the
experiment and access boundaries. The [evaluation protocol](phase-2-evaluation-protocol.md)
defines judgments, metrics and experiment discipline.

The user delegated implementation, benchmark preparation, calibration and source
review to the agent. All new source judgments must identify their reviewer as
assistant, not human. Planning approval authorized these decisions. This roadmap records the approved work and implementation evidence; task status
below distinguishes completed work from the remaining acceptance gate.

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

The original P2-01–P2-20 implementation is delivered. A fresh source-reviewed v11
assessment passed historically. The later R8 v12 assessment passed 8/14 gates and
failed six paper/evidence ranking and source-coverage gates; its warm-p95 gate passed.
Phase 2 remains open. The v12 set is spent and cannot guide tuning. Use development
data for repairs, then prepare a new source-reviewed held-out set. Current outcome and
frozen identities are in the [acceptance report](../reference/phase-2-acceptance-report.md),
and the [agent handoff](phase-2-agent-handoff.md) records guardrails.
Question text, source excerpts, candidate text, item-level results and origin ledgers
remain private; do not tune on any spent held-out set. Never read any `*origins.json`
file.

The table is the single implementation status checklist.
Tests and operational controls are added throughout, not postponed until P2-19.

| ID | Deliverable | Prerequisites | Status |
| --- | --- | --- | --- |
| P2-01 | Entry evidence and reproducible workspace | Approved plan | Complete |
| P2-02 | Search contracts, filter and access policy | P2-01 | Complete |
| P2-03 | Snapshot variants and retrieval configurations | P2-02 | Complete |
| P2-04 | Ten-question calibration and source judgments | P2-01, P2-02 | Complete |
| P2-05 | Deterministic evaluation harness | P2-03, P2-04 | Complete |
| P2-06 | BM25 lexical retrieval | P2-03 | Complete |
| P2-07 | Dense retrieval and embedding pilots | P2-03 | Complete |
| P2-08 | Fusion and consistent candidate filtering | P2-06, P2-07 | Complete |
| P2-09 | Paper, metadata and one-hop citation services | P2-08 | Complete |
| P2-10 | Cross-encoder reranking | P2-05, P2-08 | Complete |
| P2-11 | Evidence deduplication and bounded selection | P2-09, P2-10 | Complete |
| P2-12 | Development and held-out benchmark construction | P2-04, P2-05, P2-11 | Complete |
| P2-13 | Controlled prose-chunking alternative | P2-03, P2-07, P2-12 | Complete |
| P2-14 | Development experiments and acceptance limits | P2-05 through P2-13 | Complete |
| P2-15 | Default selection and experiment freeze | P2-14 | Complete |
| P2-16 | Typed paper/evidence HTTP API | P2-02, P2-09, P2-11, P2-15 | Complete |
| P2-17 | Failure, fallback and observability checks | P2-16 | Complete |
| P2-18 | Local runtime and rebuild runbooks | P2-16, P2-17 | Complete |
| P2-19 | Full verification and hosted CI | P2-18 | Complete; hosted CI passed on frozen R1–R7 code revision `586f83c` ([run 36445793795](https://github.com/avsngh-git/RAGpipeline/actions/runs/36445793795)) |
| P2-20 | Held-out evaluation and phase acceptance | P2-12, P2-15, P2-19 | R8 v12 completed: 8/14 gates passed; six quality/source gates failed; Phase 2 remains open |

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
SnapshotRepository selects per-member extraction and chunk configuration; migrations
013/014 provide resumable job plans and per-member chunk-set identity. IndexConfiguration
is stored alongside per-snapshot index build state with exact Qdrant reconciliation;
E5SmallV2Embedder is behind VectorEmbedder. Stage configuration/checkpoint persistence
and PdfEvidenceProcessor support resumable extraction and chunking.

A read-only inspection of the accepted snapshot found 100 member rows with a null
chunking configuration, selecting 44,277 current chunk IDs: 39,209 carry a chunk
configuration identity and 5,068 are legacy chunks without one. IndexRepository treats
null as all chunks for the extraction. Do not add alternate chunks under those accepted
extractions or rebuild the accepted index until P2-03.3 adds an exact-set guard.

**03.2 complete 2026-09-26:** RetrievalProfile now canonically fingerprints the snapshot
and exact chunk selection, lexical analyzer/index, embedding and vector-index identity,
optional reranker, RRF settings, candidate limits, and result-selection rules. Canonical
JSON uses sorted keys and compact UTF-8 encoding. Git revision and worktree state are
separate provenance. Candidate defaults and RRF rank constant are provisional; the
BM25S and model choices remain unselected pending their measured pilot tasks. The
accepted snapshot chunk-selection identity is sha256:cc5b7c30962ce66ad279a5ff95b0e1e6dd8aede68980292717d1a7a23ecd6f18.

**03.3 complete 2026-09-26:** ADR-0009 and migration 015 persist exact chunk IDs per
snapshot member, backfill earlier snapshots under the prior selection rule, and
prevent finalized selection changes. SnapshotRepository.create_variant_draft copies
a finalized parent's member and chunk sets and records the parent selection identity.
Chunk configuration updates replace only a draft's selected chunk rows atomically;
inspection, validation and index loading read that exact relation. The accepted
database was not migrated. Lint, format, mypy and pytest -m 'not integration' pass
(202 passed / 19 deselected). The variant integration test passes against Compose
research_test. The migration-runner integration test could not start from its expected
pristine database because local research_test already contained migrations 001–012;
migration 015 was subsequently applied by the passing variant test. No model or index
build was run.

**03.4 complete 2026-09-26:** rebuilds are serialized across processes by the
versioned index configuration's PostgreSQL advisory lock. The lock connection is
reused for PostgreSQL state reads/writes; Qdrant IDs/count and the current exact
snapshot selection are rechecked before the single ready-state update. Cancellation
marks the build reconciliation-required; process death leaves it building, so neither
state is ready. Same-configuration rebuild and cancellation tests pass, including
concurrent PostgreSQL/Qdrant integration.

**03.5 complete 2026-09-26:** snapshot selection identity now lives with ingestion
domain types. Dense search resolves and holds a PostgreSQL shared lease for one
snapshot/profile/index while querying Qdrant. Serving rejects drafts; the explicit
evaluation path permits a named draft. Both paths reject stale selection identities,
unregistered or non-ready indexes, mismatched vector configurations, and result
payloads from another snapshot/configuration. This prevents a concurrent rebuild or
snapshot-selection edit from changing the validated index during a query. The dense
service rejects profiles requiring lexical, fusion or reranking stages it cannot
execute. Four new unit tests, the profile tests, and synthetic parent/variant and
serving-boundary integration checks pass. P2-03 done condition is met: parent and
variant searches return their own exact selected chunk sets and do not mix vectors.

P2-05 is complete. P2-06.1 confirms BM25S is feasible as a candidate and 06.2 defines scientific-en-v1; continue with **P2-06.3** to build the indexes.

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

**Completed 2026-09-26:** Ten source-checked question families cover all six agreed
categories. Paper and evidence relevance are separate, comparison evidence groups are
explicit, and table judgments were checked against hashed original-PDF page images.
The missing clinical-trial family was screened against all 100 accepted papers and
nine lexical candidate papers; no direct source positive was found. The calibration
records assistant review, the one corrected table locator, source hashes, workload,
and a 30-family development/held-out decision. See
[phase-2-calibration.md](../reference/phase-2-calibration.md).

## P2-05 — Build deterministic evaluation primitives

**Inputs:** calibration schema and [evaluation protocol](phase-2-evaluation-protocol.md).

**05.1 complete 2026-09-26:** `load_calibration` reads the tracked TOML
`calibration-v1` dataset into immutable domain records. It validates schema and field
sets, IDs, source checksums/anchors, filters through `SearchFilters`, development-only
family assignment, reviewer status, labels, cross-references, and non-empty evidence
requirement groups. Eleven focused cases cover invalid IDs/references, split overlap,
invalid filters, unreviewed records and unsupported-family constraints. Verification:
`ruff check .`, `ruff format --check .`, and `mypy` pass; `pytest -m 'not integration'`
reports 219 passed / 19 deselected. No source excerpts are included.

**05.2 complete 2026-09-26:** `source_alignment.py` strictly loads a versioned
coordinate map pinned to the calibration and accepted snapshot. `matching.py` resolves
hit provenance to prose spans or table cells, unions overlap, checks document and
extraction lineage, and reports partial and full support. `source-alignment-v1.toml`
records all eight positive table anchors (942 target cells) without source excerpts.
Policy v1 requires 80% coverage per ordinary prose span, 100% for critical spans, and
complete mapped cell plus header coverage for a fully supported table anchor. Seven
tables require caption context; the semantic-chunking Table 10 alignment omits the
accepted extraction's stale caption. No units or footnotes are present in the aligned
tables; the current calibration has no direct-positive prose anchors. Python AST and
TOML parsing and `git diff --check` passed; a metadata-only accepted-snapshot query
confirmed the table context flags. `ruff` and `mypy` were unavailable in that shell;
the full evaluation-package checks later passed under P2-05.5.

**05.3 complete 2026-09-26:** `scoring.py` computes per-query paper/evidence nDCG@10,
direct MRR@10, judged Recall@20/@50, judgment coverage, evidence-group coverage, and
unsupported-query hit profiles. It preserves rank gaps, rejects rank ties, deduplicates
papers and source anchors, accumulates source coverage across result prefixes, and
requires materialized eligible paper IDs for metadata filters. Policy
`evaluation-scoring-policy-v1` records its calibration/snapshot/alignment identities;
`docs/reference/phase-2-scoring-policy.md` defines anchor-level gain, group coverage,
empty denominators, and the no-cutoff unsupported profile. Python AST parsing and
`git diff --check` passed at implementation time. The shared evaluation package now
passes Ruff, format, mypy and the non-integration suite; final results are under 05.5.

**05.4 complete 2026-09-26:** `run_records.py` defines schema v1 for per-query runs,
search attempts, returned paper/evidence identities, component scores, effective
configuration IDs, timing, structured failure categories, hardware, benchmark/code
lineage and optional scorer output. Raw records omit query text, excerpts, titles and
free-text errors; the atomic no-overwrite writer is confined to ignored
`local-reference/phase2-runs/`. Sanitized summaries omit result identities and include
an exact raw-record SHA-256 link. The contract is in
`docs/reference/phase-2-run-records.md`. Python AST parsing and `git diff --check`
passed at implementation time.

**05.5 complete 2026-09-26:** `runner.py` exposes async `evaluate_calibration` over a
`SearchService` protocol; it runs paper and evidence searches for each calibration
query, retains failed/degraded attempts, and scores only complete response pairs. Eight
synthetic behavioral tests hand-check split-boundary text matching (direct rank 2,
nDCG 0.63093), partial table support versus full group coverage, repeated-paper rank
gaps (nDCG 0.944848), duplicate chunks, ties, empty-positive denominators, unjudged
hits, failed searches and private no-overwrite run serialization. No model or network
was used. The full non-integration suite reports 227 passed / 19 deselected; `ruff
check .`, `ruff format --check .`, and `mypy` pass. P2-05's Done condition is met.

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

**06.1 complete 2026-09-26:** BM25S 0.3.11's PyPI wheel hash was verified and
installed only under `/tmp`; no project dependency was added. The read-only
accepted-snapshot export contained 100 papers/44,277 chunks (selection fingerprint
`sha256:a736b914cc350f60039a81b1944214983526c3423206109bf664abb985264dae`).
On Python 3.12.14/NumPy 2.5.3, NumPy build peak RSS was 140.07 MiB; indexing
took 0.702 s and produced a 14,136,065-byte artifact. Across two retained 250-query
warm replays per scope, mmap reload was 0.019–0.020 s; full-corpus median/p95 ranged
1.409–1.444/1.997–2.223 ms; a five-paper (1,329-chunk) eligible-only scope ranged
1.192–1.229/1.689–1.975 ms.
BM25S `weight_mask` leaks zero-score excluded rows into top-k. `get_scores` plus
eligible-row selection before top-k passed the restrictive, singleton, zero-eligible
and no-match probes; the global-top-50-then-filter path returned no eligible
hits across the ten query cases while eligible-only top-k returned 260.
Independent three-document BM25 scores/order matched. The wheel, query runs and
pilot source are retained under the ignored local-reference/phase2-runs path.
Details and limitations:
[BM25S pilot research](../research/phase-2-bm25s-pilot-research.md). The pilot
alone did not add a dependency or serving code. P2-06.3 adds the verified pin for
the implementation, with acceptance gated on P2-06.5.

**06.2 complete 2026-09-26:** `search/lexical_analyzer.py` defines the
versioned `scientific-en-v1` analyzer. It applies Unicode NFC/casefold and narrow
dash/micro-symbol normalization; retains one-character terms, acronyms, technical
compounds and their components, numeric forms and operators; and uses no stopword
removal or stemming. Nine focused behavioral tests pass, as do Ruff check/format
and mypy. On the accepted 44,277 chunks, the analyzer produced 1,917,082 tokens,
65,432 vocabulary terms and 601 empty rows in 2.012 s, versus BM25S defaults at
1,345,214 tokens, 43,469 terms and 3,685 empty rows in 0.511 s. It retained all
10 diagnostic scientific features versus one under the default analyzer; 7/10
calibration families contain a one-character query token. These are token-retention
and cost measurements, not retrieval-quality results. Policy and caveats:
[BM25S analyzer v1](../reference/phase-2-bm25s-analyzer.md). Development retrieval
evaluation may select a later analyzer revision.

**06.3 complete 2026-09-26:** `search/lexical.py` builds separate evidence and paper
BM25S indexes bound to the full retrieval profile and exact snapshot selection. Stable
row maps carry authoritative paper/evidence/document/extraction IDs and source/content
checksums, but no source text; missing title/abstract and zero-token rows are retained,
duplicate authoritative IDs fail, and repeated content under distinct IDs stays
separate. `IndexRepository.load_snapshot_lexical_inputs` reads the exact selected
chunks and both indexing-permission records in one repeatable-read, read-only
transaction; draft inputs require explicit evaluation access. OpenAlex abstracts are
reconstructed through the shared metadata helper. Five initial builder tests and two
abstract tests passed; broader builder, retriever and artifact checks are recorded below.

**06.4 complete 2026-09-26:** `LexicalRetriever` uses the versioned analyzer, computes
BM25 scores, resolves only the supplied eligible stable IDs, removes zero scores, and
then sorts/caps the eligible set. Empty eligibility, empty analyzed queries, no term
matches, unknown IDs and deterministic score ties are covered. Independent tiny-corpus
Okapi scores and ordering match within float32 tolerance.

**06.5 complete 2026-09-26:** `search/lexical_artifacts.py` writes immutable
content-addressed artifacts by atomic directory rename, saves BM25 arrays without a
text corpus, records hashes for every index file and row map, enforces private local
permissions, validates profile/snapshot/status/analyzer/scoring/row identities on
load, and reports artifact bytes. Draft artifacts require an explicit evaluation
flag. Rebuilding identical inputs resolves to the existing checked artifact.
`research-ingest index lexical-build` reads without running migrations;
`research-ingest index lexical-query` loads the same `LexicalRetriever` used by the
future search layer and supports a pre-resolved eligible-ID file. BM25S 0.3.11 is
version- and wheel-hash-pinned for runtime install. ADR-0010 records the reversible
implementation decision.

Focused builder/retriever/store/CLI/abstract tests pass (26 total); Ruff, format and
mypy pass for affected source. The loader integration assertion was added to the
disposable-services suite but not run because this workspace has no dedicated
PostgreSQL/Qdrant test URLs. The accepted review DB remains unmigrated to 015, so no
profile-compatible index was published from that DB; the lexical build command never
runs migrations and requires the persisted exact-chunk relation.

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

**Done:** met for the implementation and synthetic behavior gate. The approved
BM25S implementation and analyzer identities are recorded in
[ADR-0010](../adr/0010-phase2-bm25s-lexical-index.md); relevance-based final
selection remains P2-14/P2-15.

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

**07.1 complete; assistant-reviewed 2026-09-26:** the existing pinned
E5-small-v2 adapter's query/passage prefixes and model revision are reused by
`SnapshotDenseSearch.search_query` and `evaluate_query`. Search validates the
candidate bound and exact profile/index identity before embedding, checks the E5
revision, preprocessing, dimensions, cosine distance and token limit, then rejects
query vectors with a wrong dimension, non-finite values or non-unit L2 norm before
Qdrant access. The service hydrates ranked IDs while holding the profile lease.
`IndexRepository.hydrate_snapshot_matches` verifies exact current snapshot selection,
selected membership and both artifact and permission-review storage/indexing rights;
returned text and lineage come from PostgreSQL. Draft hydration requires explicit
evaluation access. Focused pytest of `tests/test_dense_search.py` and
`tests/test_ingestion_indexing.py`: 19 passed. Full `pytest -m 'not integration' -q`:
256 passed, 19 deselected; `ruff check .`, `ruff format --check .` and `mypy src`
pass. A live
PostgreSQL/Qdrant hydration assertion was added but not run because test service URLs
are unavailable. The implementation is synthetic-gate complete; no live E5 query
measurement was taken.

**Done:** both feasible adapters retrieve synthetic known neighbors and obey the
same filter truth table; real-model pilot measurements and index identities recorded.
A deterministic adapter substitute supports CI.

**07.2 complete; assistant-reviewed 2026-09-26:** pinned BGE-base-en-v1.5 and
measured a deterministic 12-chunk prose/table/near-limit sample on CPU and the local
RTX 3050, with batch size 4, five warm repetitions per group, explicit normalization,
peak RSS and allocator VRAM. The Windows host driver is exposed to WSL; `nvidia-smi` inside WSL reports
driver 617.14, and the default PyTorch 2.14 `cu130` runtime detects CUDA there.
The GPU pilot was rerun in that WSL environment. Project dependencies were unchanged. See
[the BGE pilot report](../research/phase-2-bge-base-en-v1-5-pilot-research.md).
The pilot supports hardware feasibility only, not retrieval quality or full-index
build-time claims.

**07.3 complete; assistant-reviewed 2026-09-26:** exact pinned fast tokenizers
counted the accepted 44,277 unique chunks with model-specific passage formatting
and special tokens. E5 maximum was 485/512; BGE maximum was 483/512; no input
exceeds either limit. The common compatible selection is the complete accepted set,
with sorted-ID SHA-256
`823bd7cd64ed89f555add9ec4967777118b8c1845b4b949e260f88987c9016f8`. Private
per-chunk records remain under ignored `local-reference/`.

**07.4 complete; assistant-reviewed 2026-09-26:** added the pinned BGE adapter and
configuration-driven adapter selection, with the example configuration at
`configs/phase2-bge-base-en-v1-5-index.example.json` (configuration ID
`sha256:c90fc73b817284ab9a7b6efd6168b06cd560247934da9e7b014c68317f562735`). The synthetic Qdrant lifecycle test builds a separate 768-dimensional collection, checks exact selected IDs and
matching readiness digests, verifies the payload configuration identity, retrieves
known synthetic neighbors, reloads the collection through a new index instance, and
rebuilds twice. The existing 384-dimensional E5 collection remains intact. BGE query
hydration and rejection of unreviewed revisions are also covered by synthetic dense
search tests. `pytest -m 'not integration' -q`: 263 passed, 19 deselected. `ruff check .`,
`ruff format --check .`, and `mypy src` pass; the missing declared BM25S dependency
was supplied only through a `/tmp` verification path. The lifecycle uses deterministic
vectors and an in-memory Qdrant fixture; no full accepted-corpus index was built or
modified.

**07.5 complete; assistant-reviewed 2026-09-26:** `SearchFilters` now maps to
Qdrant `must` conditions before top-k: inclusive year ranges and OR-within-field
`match.any` for paper, evidence-kind, and version-kind values. Index inputs carry a
versioned filter-payload marker plus authoritative paper/year/kind metadata. Serialized
rebuilds create Qdrant payload indexes, compare exact selected IDs and filter payloads
against PostgreSQL before readiness, and leave incomplete builds in
`reconciliation_required`. Filter requests reject stale index readiness and recheck
each hydrated source row using the shared filter truth table. E5 and BGE synthetic
nearest-neighbor tests both confirm restrictive filters can return a qualifying hit
below unfiltered top-1. `pytest -m 'not integration' -q`: 270 passed, 19 deselected;
`ruff check .`, `ruff format --check .`, and `mypy src` pass (BM25S is provided only
via a `/tmp` verification path). The accepted review DB is not migrated to 015, so no
accepted-index payload backfill was run; the existing collection was left untouched.
P2-07's Done condition is met; quality comparison and full-index cost remain open.


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
   the initial paper evidence score. Retain up to five distinct supporting hits in the
   accepted profile, as recorded in ADR-0012;
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
Final embedding/reranker selection happens in P2-13/14.

**10.1 complete; assistant-reviewed 2026-09-27:** the source audit and bounded
resource pilot are recorded in the [candidate report](../research/phase-2-reranker-candidate-research.md).
MiniLM-L6-v2 (233902d25c440f23af6f7d6e94d2946bac0bee0a, Apache-2.0 metadata)
and BGE reranker base (2cfc18c9415c912f9d8155881c133215df768a70, MIT metadata)
both completed CPU and WSL RTX 3050 runs, sequentially at FP32/batch 4. The same
12 development-only query/source-chunk pairs were used in every run, with no
truncation; each group has five warm timings. Peak process RSS was 1.275/1.553 GiB
for MiniLM CPU/GPU and 1.951/2.589 GiB for BGE. Peak GPU allocated/reserved memory
was 128/170 MiB for MiniLM and 1,137/1,256 MiB for BGE. Longest-group median time
per four pairs was MiniLM 0.3386 s CPU / 0.0306 s GPU and BGE 2.0602 s CPU /
0.1444 s GPU. These support feasibility only; no relevance or ranking score was
evaluated, and reranker selection remains OPEN. From WSL, nvidia-smi reported host
driver 617.14 and 4 GiB VRAM; the project PyTorch 2.14.0+cu130 runtime detected
CUDA. Raw pair IDs, timing samples and the local-only pilot script remain outside Git.

**10.2 complete; assistant-reviewed 2026-09-27:** pair format
query-source-chunk-v1 is implemented in
src/research_platform/search/reranker_pairs.py and specified in
docs/reference/phase-2-reranker-pair-format.md. It passes the query and full stored
chunk text unchanged, retains the complete EvidenceHit, and adds no paper/section
context. Model token counters measure query, evidence and special tokens with
truncation disabled. Comparative runs can supply both tokenizer revisions; if any
pair exceeds 512 tokens under any counter, the builder returns no partial list and
raises a structured budget error. Table-row-group context is passed unchanged, including header associations and
any footnotes present in the stored chunk.
Fourteen focused tests cover prose/table preservation, provenance, exact-limit and
overflow behavior. The full non-integration suite passes (332 passed, 21 deselected);
Ruff, format and strict source mypy pass.

**10.3 complete; assistant-reviewed 2026-09-27:** `search/reranker.py` binds the
adapter to the exact `RerankerIdentity` in the requested profile, enforces the
profile and adapter candidate limits, counts complete pairs and scores bounded
batches on a dedicated worker thread. A total inference timeout, strict output
alignment and finite raw-score validation fail the whole request without partial
scores. Results retain each original EvidenceHit and tie by its original fused rank.
`tests/test_reranker.py` covers fake-model batching, event-loop isolation, profile
mismatch, limits, stable ties, timeout, over-budget inputs, malformed scores, output
alignment and partial-batch failure. Focused suite: 24 passed. The full offline suite passes
(342 passed, 21 deselected) using the existing temporary BM25S verification path;
full Ruff and formatting pass (158 files), and strict mypy reports no issues in 67
source files. A timeout cannot terminate an already-running inference thread; a
timed-out request returns no scores while that worker finishes. No weights or
dependencies were added. See the handoff for exact commands and limitations.

**10.4 complete; assistant-reviewed 2026-09-27:**
`search/reranker_results.py` applies result ordering only when scores cover the exact
candidate pool and match the selected model, full retrieval-profile identity and
SHA-256 of the exact query. It requires hybrid fusion provenance and checks every
input's fused rank before updating the visible EvidenceHit rank. Lexical, dense and
original fusion scores/ranks remain unchanged; reranker rank/raw score are separate.
Omitted, substituted, duplicated, modified, already-reranked or non-fused evidence is
rejected. Tests cover provenance retention, candidate-pool changes and query/profile/
model identity mismatches; focused reranker/pair suite: 28 passed. The full offline
suite passes (346 passed, 21 deselected) using the existing temporary BM25S
verification path; Ruff, format, strict source mypy and `git diff --check` pass.

**10.5 complete; assistant-reviewed 2026-09-27:**
`search/reranker_models.py` loads only the exact reviewed MiniLM/BGE revisions from
the local cache, with remote code disabled. It explicitly preserves raw logits using
identity activation and disables softmax. Missing optional runtime or weights,
unavailable CUDA, device OOM, inference timeout, invalid/alignment output and pair
budget errors become safe failures. `search/reranker_service.py` returns the exact
original fused candidates on failure and reports the failed model/revision/type
without query, evidence or raw exception text. Fake tests cover the failure branches.
Both pinned real models then passed local-only WSL CUDA smoke and the profile-bound
adapter plus provenance mapper on one synthetic pair each (19 tokens); no corpus text
or new download was used. Full offline suite: 356 passed, 21 deselected using the
existing temporary BM25S verification path; Ruff and format pass (162 files), strict
mypy reports no issues in 70 source files, and `git diff --check` passes. No retrieval-quality score was computed; candidate
selection remains OPEN. P2-10's Done condition is met.

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

**11.1 complete; assistant-reviewed 2026-09-27:** `evidence_deduplication.py`
removes exact chunk repeats and fully covered source intervals. Text coverage is
scoped to extraction/section; table coverage uses body-row intervals and exact
oversized-cell token intervals, excluding repeated headers from content coverage.
Partial overlaps and unresolved mappings are retained. Similar text across different
extractions or papers is not deduplicated. Omission records identify retained covering
hits. Fifteen synthetic cases pass. The offline suite reports 371 passed / 21
deselected; Ruff check and format pass (165 files), strict mypy passes (71 source
files), and `git diff --check` passes. See the
[evidence deduplication policy](../reference/phase-2-evidence-deduplication.md).
Continue with configurable per-paper bounds in 11.2.

**11.2 complete; assistant-reviewed 2026-09-27:** `evidence_selection.py` applies
the profile-bound `evidence_per_paper_limit` independently to each paper, keeps
the highest-ranked hits in global rank order, and records each cap omission with
chunk and source IDs. The provisional default is 3, maximum 5; changing the cap
changes the retrieval-profile ID. This is distinct from `paper_support_limit`,
which bounds passages attached to a paper result. Eighteen focused selector,
profile-identity and grouping tests pass. The offline suite reports 377 passed / 21
deselected; Ruff check and format pass (168 files), strict mypy passes (72 source
files), and `git diff --check` passes. Quality/diversity tradeoffs remain for P2-14.
See the [per-paper evidence selection policy](../reference/phase-2-evidence-selection.md).
Continue with table context preservation in 11.3.

**11.3 complete; assistant-reviewed 2026-09-27:** `table_context.py` enriches table
hits with typed header rows, selected body rows or exact oversized-cell segments,
caption, units, footnotes, merged-cell ranges, header references and source IDs.
Row-group text remains unchanged and cell-segment values are not clipped. Oversized
cells return only required header cells; unresolved source/table mappings fail closed.
The optional context is included in the typed EvidenceHit API schema. Eight focused
table-context cases pass. The offline suite reports 385 passed / 21 deselected; Ruff
check and format pass (171 files), strict mypy passes (73 source files), and
`git diff --check` passes. See the
[table evidence context policy](../reference/phase-2-table-evidence-context.md).
Continue with total result and context budgets in 11.4.

**11.4 complete; assistant-reviewed 2026-09-27:** `evidence_budgets.py` applies a
50-hit page maximum, the profile's per-paper cap, and shared character/token budgets
to evidence search. Paper search applies the same budgets across supporting evidence
while preserving paper ranks and scores. The provisional budgets are 12,000 characters
and 4,000 unicode-token-v1 tokens (hard maxima 24,000 / 8,000); changing either budget
or token policy changes retrieval-profile schema 2 identity. Whole hits that do not
fit are omitted with chunk/source IDs and each exceeded reason; lower-ranked complete
hits may still fit. Existing source-linked oversized-cell segments may be selected
intact. Nine focused budget cases pass. The offline suite reports 394 passed / 21
deselected; Ruff check and format pass (174 files), strict mypy passes (74 source
files), and `git diff --check` passes. Quality tradeoffs remain for P2-14. See the
[evidence result budget policy](../reference/phase-2-evidence-result-budgets.md).
P2-11.5 completion follows.

**11.5 complete; assistant-reviewed 2026-09-27:** search contracts now include an
exact `eligible_count`, a derived status separating empty filter scope from zero
returned candidates, and the fixed `ranking_only` interpretation. Lexical results
retain eligible-record counts separately from positive term matches; dense results
expose the validated snapshot/filter count; hybrid retrieval fails closed if its
branches disagree. Evaluation attempt records persist these values under schema 2.
No relevance cutoff is applied; future cutoffs require calibration and freeze for the
exact effective mode/profile. Focused and full-suite verification is recorded in the
[agent handoff](phase-2-agent-handoff.md) and
[search result semantics policy](../reference/phase-2-search-result-semantics.md).
P2-11 is complete; P2-12.2 is recorded below, and P2-12.3 is next.

**12.1 complete; assistant-reviewed 2026-09-27:** the ten-family calibration and
its measured review workload are recorded in
[phase-2-calibration.md](../reference/phase-2-calibration.md). The frozen plan keeps
all ten calibration families in development and sets 30 total families (20
development, 10 held-out), six category floors, prose/table/negative-finding
coverage, top-50 evidence and top-20 paper pools per core profile, caps of 200 unique
evidence items and 80 unique papers per family, and a 12-hour review budget. Review
effort is remeasured after five newly pooled development families. The ten-family
test supports directional conclusions only. See the
[benchmark sampling plan](../reference/phase-2-benchmark-sampling-plan.md) and its
TOML manifest. At the P2-12.1 freeze, continue with P2-12.2.

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

**12.2 complete; assistant-reviewed 2026-09-27:** the q11–q20 development pools
combine seven pinned retrieval profiles with an independent source-found channel.
Each profile contributed up to 50 evidence and 20 evidence-derived paper
candidates; three lexical metadata streams contributed up to 20 papers each.
Blinded unique pools contain 1,216 evidence candidates and 341 papers across ten
families. No family reached the 200-evidence or 80-paper cap. Per-family depths,
profile IDs, truncation, source-scan coverage, exclusions and bias notes are in the
private pool manifest and origin maps under
`local-reference/phase2-runs/benchmark-v1/review-pools-v1/`. Source review is
underway: q11 has one paper and two evidence anchors judged. q12 has one paper and
three prose evidence candidates judged; its table row groups await visual review.
The q12/q14 table-candidate audit found q12's reviewed Table 1 anchor has no
corresponding pooled row-group card, the three Table 2 cards cover only partial
row blocks, and q14's Table 7 source-list lead is absent from the pool. Exact
accepted-PDF checksums and candidate identities are recorded in [the table audit]
(../research/phase-2-q12-q14-table-candidate-audit.md). Official-PDF screenshot
calls returned no viewable image in this environment, so table candidates remain
unjudged; text-only suggestions in that note are not labels. All other q11
candidates, 15 q12 papers, and 103 q12 evidence candidates remain
unjudged. q13 has two papers and six pooled evidence candidates source-reviewed; a
seventh source anchor has no current pooled candidate mapping, and 40 papers / 103
evidence candidates remain unjudged. Its two LongRAG table leads remain unjudged. q14
has one paper and eight prose evidence candidates source-checked, with 15 papers and
99 evidence candidates unjudged; its table-row candidates await visual review. q15
has four near-match papers and four evidence cards source-checked; the full-corpus scan
matched one MTEB passage about SPECTER training on citation graphs, not citation-edge
traversal for RAG. No direct supporting work was found within the snapshot under this
review procedure; 44 papers and 137 evidence candidates remain unjudged. q16 has one paper and 11 prose evidence cards source-checked, with 14 papers and 92
q16 evidence candidates unjudged; the review separates response metrics from generated-
document human ratings and records terminology variations. q17 has two papers and six
prose evidence cards source-checked; 35 papers and 110 evidence candidates remain
unjudged. The comparison records CodeRAG-Bench's four coding-task categories, five
retrieval-source types, and retrieval, generation, and end-to-end evaluation, alongside
BERGEN's QA-centered coverage and configurable retrieval, reranking, generation, and
training pipeline. Both accepted PDF checksums match their snapshot records. q18 has two papers and four
pooled prose evidence cards source-checked, plus a source-only legal text-offset anchor;
40 papers and 140 evidence candidates remain unjudged. QASPER is the closest research-
paper case, with paragraph/figure/table evidence units and separate answer/evidence
scores; the chunking study evaluates evidence-sentence retrieval and generated answers.
LegalBench-RAG stores exact character offsets in legal text and evaluates retrieval, not
answer generation. No exact character or PDF-coordinate judgments for research PDFs were
found among the reviewed candidates. q19 has three near-match papers and five evidence
cards source-checked; all five independent scan leads were reviewed and mapped to blinded
cards. Forty-seven papers and 138 evidence candidates remain unjudged. Its frozen scan
covered all 100 papers / 44,277 selected chunks, matching five chunks in three papers and
zero title or abstract records. The matches concern upstream LaMDA pretraining,
unquantified PromptReps document encoding, or a review’s future recommendations; no
measured local RAG energy per query was found under the recorded scan and review.

q20 has five papers and 20 evidence cards source-checked; all eight independent
scan leads were reviewed and mapped to pooled cards. Its year-filtered scan covered
21,061 chunks across 39 papers and matched 11 chunks in five papers, with one
title/abstract match. LegalBench-RAG and the 2025 Summary-Augmented Chunking study
report retrieval benchmark evidence; the latter explicitly leaves end-to-end
evaluation to future work. Legal experts contribute annotations, prompt design, or
qualitative interpretation. No reviewed study reports practicing lawyers using a
system on live client matters. An in-snapshot systematic review's “practicing
attorneys” row describes intended benchmark use; its cited 2024 primary study uses
author-constructed queries and researcher assessment. LegalBench-RAG's abstract
says 6,858 query-answer pairs while §3.3.1 says 6,889. The systematic-review table
was text-extracted but not visually verified because this WSL environment has no
PDF renderer. q20 remains partial: 25 paper and 104 evidence candidates are
unjudged, its lexical scan is bounded, and its review is marked partially
unblinded after accidental origin-map output exposure; no labels used rank or score. Continue with 12.3.

**Historical P2-12.3 held-out source checkpoint at initial review; assistant-reviewed 2026-09-27 (superseded by the completion record below):** q21–q30
canonical query text and source anchors are frozen before pooling. The family split
manifest binds the held-out query SHA-256 together with the development query hash.
Held-out coverage meets all six category floors, with three numeric-table, three
direct-positive-prose, and four negative/mixed families. The sanitized source audit
is [phase-2-heldout-question-source-audit.md](../research/phase-2-heldout-question-source-audit.md);
private source and scan records are under
`local-reference/phase2-runs/benchmark-v1/`. A text-layer scan verified all 100
accepted PDFs and 1,705 pages, with no textless PDFs. q25 matched one paper/two pages,
q26 seven papers/24 pages, and q27 16 papers/64 pages for their recorded screening
terms. The sources and limits are recorded in the audit. Historical blinded q21–q30 v1 cards contain 1,601 evidence and 245 paper candidates;
q21 is excluded after its private ranks and scores were accidentally exposed by a broad
filename glob during card sampling. Uncontaminated q22–q30 v1 cards contain 1,440
evidence and 223 paper candidates. The v2 split binds q22–q30 plus source-checked q31,
frozen before replacement retrieval. Its source map contains 18 anchors and 36
accepted/fixed-window chunk links. Fresh v2 retrieval and reviewer cards remain pending.
Relevance judgments and coverage resolution remain open; no held-out scores have been
used for configuration choices.
q11–q20 candidate review remains partial, so P2-12 is in progress. q20 remains
disclosed as partially unblinded; all `*origins.json` files remain excluded from
review.

**P2-13 implementation checkpoint, assistant-reviewed 2026-09-27:** the
versioned fixed-window prose strategy is implemented in the existing ingestion
processor. Its tracked baseline uses 480 E5-small-v2 tokens with 64-token overlap,
six table rows per group, section-ordinal reading order, and a two-newline synthetic
separator. Existing section-aware configuration IDs remain stable. Fixed windows
store every section-local source range, chunk-local range, heading path, and
available source location in chunk metadata; cross-section units leave the legacy
single-section offsets and location empty. Table rendering still uses the existing
path. Source matching and deduplication now union the constituent spans, the
framework-independent evidence contract carries them, and dense hydration restores
them from authoritative PostgreSQL rows. No migration was needed.

The existing extraction fingerprint is shared across chunk strategies; the fixed
strategy has its own chunking revision and therefore selects new variant chunks.
The reprocessing integration test uses two sections and checks multi-span
hydration. It passes against a disposable PostgreSQL/Qdrant project. A full fresh-DB
integration run also exposed an outdated snapshot-finalization fixture: it inserted
snapshot members directly but omitted the exact selected-chunk rows required by
migration 015. The fixture now uses `SnapshotRepository.add_member`; all 19 live
integration tests pass. Current offline verification reports Ruff and formatting
clean, mypy clean across 74 source files, and 403 tests passed / 21 integration tests
deselected. The local `sci_research_agent` environment still lacks BM25S; checks used
the already hash-verified 0.3.11 package staged under `/tmp`. This implementation
checkpoint is superseded by the P2-13 completion record below. Real-variant index
measurement is recorded here; final fairness and paired results are in the
[fixed-window audit](../research/phase-2-fixed-window-source-fairness-audit.md) and
[fixed-window chunking note](../reference/phase-2-fixed-window-chunking.md).

**P2-13.4 variant build and resource measurement; assistant-reviewed 2026-09-27:**
The isolated 100-paper variant `c3447473-a9f7-4d8c-93c0-e45ebcab763f` reuses the
accepted snapshot's member/extraction rows and exact 5,068 selected table/figure
chunk IDs. It selects 3,427 fixed-window prose chunks (8,495 chunks total). The
E5-small-v2 dense index built in 137.2 seconds across 531 batches, with sampled peak
VRAM 459 MiB, process RSS 1.43 GiB and Qdrant storage delta 708,175,469 bytes.
BM25S 0.3.11 built 8,495 evidence rows and 100 paper rows in 4.27 seconds; artifact
sizes were 17.1 MB and 67.5 KB. Private run manifests and measurements are under
`local-reference/phase2-runs/fixed-window-20260927/`. The accepted snapshot and its
retained indexes were unchanged. At this earlier checkpoint, paired development
quality, source-match fairness, and tokenizer checks remained open; the P2-13
completion record below closes them.

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

**P2-13 complete; assistant-reviewed 2026-09-27:** variant
`c3447473-a9f7-4d8c-93c0-e45ebcab763f` reuses the accepted 100-paper selection
and extraction rows while selecting 3,427 fixed-window prose chunks and the same
5,068 table/figure chunks (8,495 total). Its E5 index configuration is
`sha256:93ca6395843fe829fa58e550c24ecfceddf79c39874927c7e948fd08ac973844`.
Existing fixed-window, extraction-reuse, table-invariance, source-mapping, and
deduplication tests pass (46 focused tests); the live synthetic rechunk/reuse test
passes against disposable PostgreSQL/Qdrant (1 passed). Both tokenizer checks stay
under 512 tokens: the longest mapped anchor inputs were 359 E5 tokens / 357 BGE
tokens; all 301 fixed-window chunks in anchor-bearing papers were at most 485 E5 /
483 BGE tokens. All 27 reviewed positive prose candidate intervals map exactly to
their source text and reach full source coverage in both chunk sets.

The paired dense-E5 run uses q11–q19, identical queries and filters, pinned
`intfloat/e5-small-v2` revision
`e8b23a92af33fd81c865283d505f8f058a570cc8`, and top 50. Seven families
contribute 27 reviewed positive prose anchors; q15 and q19 have no positive prose
anchors. Source-anchor recall at ranks 1/5/10/20/50 is section-aware 2/4/7/9/13 of
27 and fixed-window 1/4/6/9/13 of 27. At rank 10, one positive family improved,
five tied, and one declined; mean paired family change was -1.9 percentage points.
This sample does not support a fixed-window quality advantage. Calibration table-only
questions were not part of this prose-specific comparison; table chunks are identical
and remain in ranked candidate positions.

The paired run used a disposable database and Qdrant. To apply the same filters, the
accepted parent vectors were read-only mirrored into the test collection; all 44,277
point IDs matched the exact selected parent IDs, and only test metadata was enriched
with the current filter marker. The accepted database and Qdrant collection were not
changed. q20, q21, all held-out families and held-out scores were excluded. Raw
development ranks/scores remain mode-0600 under ignored `local-reference/`; the
sanitized metric table, profile identities, artifact hashes, reproduction paths and
limitations are in the [fixed-window audit](../research/phase-2-fixed-window-source-fairness-audit.md).

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

## P2-14–P2-19 local checkpoint — 2026-09-27

P2-14's development comparison and predeclared quality/runtime gates are in the
[development report](../research/phase-2-development-report.md). P2-15 freezes
MiniLM over Hybrid E5 with whole-pool reranked-to-hybrid fallback, five evidence
items per paper, and no unsupported-query cutoff. The canonical serving profile is
`sha256:243e3d5923ee930940a29cf4ba79db2392cf4a5bfe777a54cedd2a316fd22870`; the
acceptance configuration digest is
`sha256:6beb525c6a5d76b2bcf28dd0c03bce527872ca462ce44dceba4ea5ce383590bb`.
The profile was corrected to bind its isolated filter-ready Phase 2 collection, which
is the collection used by development evaluation. Model, ranking, selection,
thresholds, accepted corpus and held-out inputs did not change.

P2-16–P2-18 are implemented and documented in
[phase-2-search.md](../operations/phase-2-search.md). The real-model WSL smoke check
exercised paper search, table-filtered evidence search, a zero-eligible filter,
paper metadata, references and citations. All returned their expected successful
responses. Five warm table-filtered requests measured 1,128.81–1,245.15 ms; the
nearest-rank p95 was below the frozen 1,500 ms limit. The isolated dense collection
was rebuilt and reconciled against all 44,277 selected evidence units. The accepted
Phase 1 index was retained.

Local P2-19 checks on the updated exact Linux lock: Ruff lint and formatting pass;
strict mypy passes across 79 source files; the complete CI-equivalent unit/API/
evaluation/PostgreSQL/Qdrant suite reports 445 passed in 8.90 seconds, including 21
live integration tests against freshly created no-volume services. Migration rerun
passes; `pip check` reports no broken requirements; `pip-audit --skip-editable`
reports no known vulnerabilities (the editable project itself is skipped). The
Docker image builds with a 47.45 KB context containing only selected runtime
manifests. The rebuilt image imports BM25S/NumPy, exposes the CLI, and passes
`pip check`. A missing NumPy runtime dependency was found by the image smoke check,
then added as pinned NumPy 2.5.3 with its BLAS libraries in the Conda specification
and exact lock. `git diff --check` passes. Hosted CI passed on sanitized revision
`b1c12320c223518dca926f4de128d25a4c6ff4eb`
([run 36344475763](https://github.com/avsngh-git/RAGpipeline/actions/runs/36344475763));
P2-19 is complete. P2-20 ran against the frozen v3 assessment and failed paper
nDCG@10, evidence nDCG@10, reranker fallback fraction, and warm p95. The completed
aggregate report is [phase-2-acceptance-report.md](../reference/phase-2-acceptance-report.md).
At this historical checkpoint, P2-20's Done condition was unmet because the v3
held-out gate failed. Do not tune on v3 or reuse it as an unseen test. The later v11
assessment completed P2-20 with a fresh held-out set and unchanged profile/limits.

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
| Quality/latency thresholds and default | P2-13/14 | Freeze before held-out evaluation |
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

**P2-12 complete; assistant-reviewed 2026-09-27:** the active v3 split binds the
development and held-out question manifests by SHA-256 and assigns 20 development
and 10 held-out families. All six category floors and held-out modality floors are
met. All q11–q20 development cards (1,216 evidence, 341 paper candidates) and
q22–q31 held-out cards (1,581 evidence, 245 paper candidates) have resolved labels.
The q11–q20 source notes contain 83 anchors: 77 map to review candidates and six
are retained as source-only/out-of-scope anchors. All 21 active held-out anchors map
to review candidates, with 34 anchor-to-candidate links. The [dataset card](../reference/phase-2-benchmark-dataset-card.md), [coverage audit](../research/phase-2-benchmark-source-coverage-audit.md), and [held-out source audit](../research/phase-2-heldout-question-source-audit.md) record counts, hashes, modality coverage and limits. q20 remains partially unblinded and is excluded from tuning; q21 is excluded after held-out rank/score exposure. No held-out scores have informed configuration choices. All `*origins.json` files remain outside the review path.


## Historical v9 P2-20 outcome — assistant-reviewed 2026-09-28

The v9 result and its gate outcome are retained in the aggregate
[acceptance report](../reference/phase-2-acceptance-report.md). The v9 set is spent
and sealed from selection.

## Historical v10 P2-20 outcome — assistant-reviewed 2026-09-28

The v10 held-out assessment completed against the frozen profile and unchanged
thresholds. It passed 13 of 14 gates; warm p95 was 1,602.2 ms against the 1,500 ms
maximum. Every quality, source-coverage, hard-failure, fallback, cold-load and CUDA
allocation gate passed. The sanitized [acceptance report](../reference/phase-2-acceptance-report.md)
contains the profile aggregates, paired bootstrap intervals, category summaries,
resource measurements and gate values.

The v10 set is spent and sealed from selection. Do not inspect its item-level outcomes
or change the profile or limits based on them. Any performance repair must be grounded
in calibration/development evidence, preserve the locked paper aggregation rule and
be assessed on a fresh source-reviewed held-out set. P2-20 and Phase 2 remain open
until every frozen gate passes.

A subsequent development-only search-service timing replay measured paper-search p95
of 1,433.45 ms and evidence-search p95 of 1,336.92 ms on 95 samples per operation.
At the time, this did not clear the v10 held-out latency failure; the later v11
assessment below is the current acceptance evidence. See the
[development report](../research/phase-2-development-report.md).


## Current v11 P2-20 outcome — assistant-reviewed 2026-09-28

A fresh source-reviewed ten-family assessment passed every frozen quality and
operational gate without changing the selected profile or numeric limits. The selected
profile's warm p95 was 1,485.8 ms against the 1,500 ms limit; aggregate quality, source
coverage, failure, fallback, cold-load and CUDA-allocation results are recorded in the
[acceptance report](../reference/phase-2-acceptance-report.md). The v11 set is spent and
sealed from tuning. P2-20 and Phase 2 were complete at that historical checkpoint; Phase 2 was later reopened for R1–R8.

## Owner-directed warm-latency gate — assistant-reviewed 2026-09-28

The v10 held-out result remains 1,602.2 ms against its original 1,500 ms gate. The
owner has said 1.6 seconds is reasonable and approved a new 2,000 ms maximum warm-p95
criterion for the fresh R8 assessment. The
[acceptance-v10 configuration](../../benchmarks/phase2/acceptance-v10.toml) binds
`phase2-benchmark-v12`; its SHA-256 is
`dd75323a5fa263dc29f91056c646e001756e76192cfa6025ec59148709a50377`. The existing
30-second request deadline is a separate timeout, and every other acceptance gate is
unchanged. Preserve historical outcomes and all spent held-out sets. See
[ADR-0013](../adr/0013-phase2-warm-latency-acceptance.md); the fresh R8 assessment is
recorded below and in the acceptance report.


## Current R8 v12 outcome — assistant-reviewed 2026-09-28

The frozen assessment passed 8 of 14 acceptance gates. The selected profile's warm
p95 was 894.349 ms across 300 measured HTTP requests, below the 2,000 ms limit. Six
gates failed: paper nDCG@10; evidence nDCG@10, direct MRR@10 and judged Recall@20;
source-anchor Recall@50; and the fraction of positive families with a source hit at
@10. P2-20 and Phase 2 remain open. The v12 set is spent: do not inspect item-level
results or tune from its aggregate profile comparison. Continue with development data,
then freeze and assess a newly source-reviewed set. See the
[acceptance report](../reference/phase-2-acceptance-report.md) for all gate values.
