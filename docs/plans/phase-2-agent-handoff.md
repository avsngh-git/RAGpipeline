# Phase 2 — Agent handoff

Updated: 2026-09-27. Plan approved; P2-01–P2-11 complete; continue with P2-12.1.

## Start here

1. Follow AGENTS.md and read the authoritative source of truth in full.
2. Read the [roadmap](phase-2-retrieval-evaluation.md), then the first pending task
   whose prerequisites are satisfied. Continue at **P2-12.1**.
3. Read the [evaluation protocol](phase-2-evaluation-protocol.md) when working on
   judgments, experiments or scoring. Read ADR-0008 for variant/access boundaries.

The planning interview is complete. Preserve its decisions; investigate current
facts yourself. Do not restart the interview or select different technology merely
because another agent prefers it. Measured settings are deliberately deferred to
named tasks and must be recorded there.

## Delegation and working style

The user explicitly delegated all Phase 2 implementation, calibration, benchmark
preparation and source review for now. Once asked to begin Phase 2, execute bounded
substeps autonomously, explain changes/tests briefly and update progress. The earlier
user-writes-code default does not apply to this delegated phase. No recurring human
annotation gate is required. Mark new judgments assistant-reviewed; record source
checks, uncertainty and sampling limits. Escalate actual contradictions or material
changes beyond the approved scope, rather than routine reversible choices.

The user's preference is economical model use for routine work. This handoff does
not change the active model. Never infer that an unchecked task is complete.
The user explicitly authorizes local commits when they help maintain a coherent
working tree. Do not push, publish tickets, use paid compute, or deploy publicly.
Preserve the user's existing worktree and publication workflow.

## Current baseline and traps

- Current entry revision: `0458c9c7f28a5eceac5ca939fe1e17a59e870c1b`.
  [Hosted CI 36241133854](https://github.com/avsngh-git/RAGpipeline/actions/runs/36241133854)
  passed on that exact revision. It changes docs/configuration only relative to
  the remediation revision `d28e1adc299d6199774c78a2d63cb3eb0870d5ab`; no local
  test suite was rerun during P2-01.
- P2-01 removed the root `/docs/` ignore rule. Sanitized project documents are
  eligible for version control and were committed by the user at
  5f2a7db5835df2fa6b89692a06701d564901a8bb. Local-only manifests, excerpts and
  PDFs remain excluded from Git.
- The accepted snapshot is `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` in
  **research_phase1_review**, not default **research**. P2-01 applied migrations
  013/014 after a verified local backup; read-only validation, 100 source checksums
  and snapshot-scoped reconciliation all pass at 100 papers / 44,277 chunks. The
  running API still targets `research`; bind Phase 2 operations to the review DB.
- Qdrant `phase1-e5-small-v2` also contains the retained ten-paper draft's points.
  Every query must bind a snapshot and compatible profile; collection count is not
  corpus membership. New model/chunk variants must not overwrite the accepted set.
- All 100 permission records allow storage/indexing and disable passage display.
  The approved trusted private-local inspection policy is separate from public
  output. Never change permissions by interpreting an API flag as authorization.
- Reuse ingestion/indexing.py, embeddings.py, snapshots.py, evidence persistence
  and migrations 013/014. They provide versioned indexing, query embeddings,
  finalization checks and separate extraction/chunk checkpoints. Verify applied
  schema before querying with newer code; tests use isolated services.
- Existing query_snapshot handles snapshot filtering; richer filters, lexical
  search, fusion, reranking, evaluation and the new API remain Phase 2 work.
- Existing draft preview is not the finalized evidence service. The API currently
  exposes health/readiness only. New routes call shared services.
- Model shortlist and hardware memory figures are not feasibility proof. Remeasure
  current resources. Keep synthetic CPU CI independent of model downloads.
- JSON is broadly ignored. Use deliberately tracked sanitized config/fixture paths;
  full text, source PDFs and private review artifacts stay outside Git.

## Progress and stop rules

- **P2-02 complete** in the user commit `5f2a7db5835df2fa6b89692a06701d564901a8bb`: search contract, framework-independent contracts,
  strict HTTP schemas, fail-closed filter matching, and server-owned evidence access.
- **P2-03.1 inventory complete:** existing snapshot/index/stage persistence was
  inspected. The accepted snapshot has 100 members and 44,277 currently selected
  chunks. All 100 member chunking IDs are null; 39,209 selected chunks carry a config
  ID and 5,068 are legacy chunks without one. IndexRepository currently treats null
  as every chunk under an extraction. Do not add variant chunks under those accepted
  extractions or rebuild its index until P2-03.3 guards the exact selected set.
- **P2-03.2 complete:** src/research_platform/search/profiles.py defines strict,
  canonical profile and chunk-selection identities. The accepted snapshot selection
  hashes to sha256:cc5b7c30962ce66ad279a5ff95b0e1e6dd8aede68980292717d1a7a23ecd6f18.
  No lexical dependency or model choice was made.
- **P2-03.3 complete:** migration 015 persists each snapshot's exact selected chunk IDs,
  backfills legacy selections, and blocks mutation after finalization. Variants copy
  a finalized parent's paper/document/extraction and exact chunk selection, and retain
  the parent's canonical selection identity in lineage. The loader, inspection and
  finalization checks use the persisted selection. See ADR-0009 and the roadmap.
- Verification: ruff check ., ruff format --check ., and mypy pass;
  pytest -m 'not integration' reports 202 passed / 19 deselected; the focused
  variant integration test passes on Compose research_test. The separate migration
  runner test expects a pristine test DB, but local research_test already contained
  migrations 001–012 and that test failed before applying pending migrations.
  Migration 015 was then applied successfully by the variant integration test.
  The accepted database was not migrated. Hosted CI has not run.
- **P2-03.4 complete:** index builds for a configuration are serialized with a
  PostgreSQL advisory lock. The same connection carries the lock and build-state
  operations, avoiding pool deadlock. Before readiness, Qdrant identities/count and
  the source snapshot's exact selection are checked again. Cancellation records
  reconciliation_required; hard process interruption leaves building. Offline tests
  report 204 passed / 19 deselected, and the concurrent index integration test passes.
- **P2-03.5 complete:** dense search resolves a snapshot selection and holds a shared
  PostgreSQL lease while checking the exact selected chunk digest, stored vector
  configuration, ready state and Qdrant payload identities. Finalized snapshots are
  available through serving search; drafts require the explicit evaluation method.
  The profile-bound service rejects model/index mismatches and unavailable lexical,
  fusion or reranking stages. Ruff, format, mypy and the offline suite pass; the two
  targeted PostgreSQL/Qdrant integration tests pass. A synthetic parent/variant pair
  returns only its own exact selected chunk IDs from separate indexes. See P2-03.5
  in the roadmap for details.
- P2-03 is complete. No Phase 2 model was downloaded, no index was built outside
  synthetic integration, and the accepted source corpus was not changed.
- **P2-04 complete:** docs/reference/phase-2-calibration.md contains ten
  assistant-reviewed, PDF-source-checked development families across all six required
  categories, separate paper/evidence labels, comparison groups, nine table regions
  across five answer-bearing PDFs, and a source-audited missing-evidence case over
  all 100 accepted papers. Nine lexical candidate papers were inspected; the clinical
  chunking/RAG paper, public-health RAG, and clinical extraction RAG are label-1
  near-matches, not trial positives. The table packet used stale extraction IDs for
  two papers; calibration records current accepted extraction IDs and pins visual
  anchors to PDF checksums. Calibration effort was about 32 minutes. The decision is
  30 families (20 development, 10 held out), up to 200 unique evidence candidates and
  80 paper candidates per family, with a 12-hour review budget. No retriever output or
  held-out score exists yet. The source-review and split limitations are in the
  calibration file.
- **P2-05.1 complete:** `src/research_platform/evaluation/calibration.py` loads
  `benchmarks/phase2/calibration-v1.toml` into immutable typed records and rejects
  malformed fields, duplicate IDs, cross-split family overlap, invalid source/filter
  references, unresolved reviewer status, and malformed evidence groups. Eleven
  focused loader tests pass; `ruff check .`, `ruff format --check .`, and `mypy` pass;
  `pytest -m 'not integration'` reports 219 passed / 19 deselected. P2-05 remains in
  progress; continue with source matching in 05.2.

- **P2-05.2 complete:** `source_alignment.py` loads the coordinate manifest pinned to
  calibration and snapshot; `matching.py` checks canonical text spans and table cells,
  unions duplicate/overlapping coverage, and validates hit lineage. Policy
  `source-match-policy-v1` freezes 80% ordinary-span and 100% critical-span coverage,
  plus full mapped-cell/header coverage for a full table match. Eight positive table
  anchors are aligned (942 target cells); there are no positive prose anchors in this
  calibration. Details and limitations are recorded in
  `docs/reference/phase-2-source-matching.md`. Ruff and mypy were unavailable in this
  shell; Python AST/TOML parsing and `git diff --check` passed.
- **P2-05.3 complete:** `scoring.py` computes per-query paper/evidence nDCG@10, direct
  MRR@10, judged Recall@20/@50, judgment coverage, evidence-group coverage, and
  unsupported-query hit profiles. It preserves rank gaps, rejects duplicate ranks,
  deduplicates papers and source anchors, accumulates source coverage across result
  prefixes, and requires materialized eligible IDs for metadata filters. Policy
  `evaluation-scoring-policy-v1` is linked to the calibration, snapshot, and alignment
  identities. Scoring rules are recorded in `docs/reference/phase-2-scoring-policy.md`.
  Python AST parsing and `git diff --check` passed at that checkpoint; full evaluation
  checks passed during P2-05.5.
- **P2-05.4 complete:** `evaluation/run_records.py` defines schema v1 for per-query
  run lineage, search attempts, result IDs/ranks/component scores, effective config
  IDs, timings, failure categories, hardware and optional scores. Raw writes are
  atomic, no-overwrite, private-permission JSON files under ignored
  `local-reference/phase2-runs/`; query text, excerpts, titles and exception messages
  are omitted. Sanitized summaries carry the raw record hash and omit result IDs.
  The contract is documented in `docs/reference/phase-2-run-records.md`. Python AST
  parsing and `git diff --check` passed at implementation time.
- **P2-05.5 complete:** async `runner.evaluate_calibration` runs each query through an
  injected `SearchService` protocol and preserves failures. Eight synthetic tests
  cover tied ranks, zero-positive metrics, duplicated papers/chunks, split-boundary
  prose, partial table support, unjudged hits, failed requests and serialization.
  `pytest -m 'not integration'`: 227 passed / 19 deselected; `ruff check .`,
  `ruff format --check .`, and `mypy` all pass. No model or network was used.

- **P2-06.1 complete:** PyPI release/API/license and the exact wheel were verified;
  BM25S 0.3.11 was installed only in the private temporary pilot. The accepted
  snapshot export was read-only and permission-gated at 100 papers/44,277 chunks.
  Build peak RSS was 140.07 MiB; index size 14,136,065 bytes; build/save took
  0.702/0.233 s. Across two retained 250-query warm replays per scope, mmap reload
  was 0.019–0.020 s; full-corpus median/p95 ranged 1.409–1.444/1.997–2.223 ms;
  five-paper restricted median/p95 ranged 1.192–1.229/1.689–1.975 ms. A synthetic test showed `weight_mask` can return excluded
  zero-score rows; `get_scores` followed by eligible-only top-k passed full,
  restrictive, singleton, empty-eligibility and no-match probes. A small independent
  BM25 score/order example passed. The pilot itself did not add a dependency or
  service code. P2-06.3 later pinned the measured wheel for implementation. See
  `docs/research/phase-2-bm25s-pilot-research.md` for artifact, corpus and timing
  identities, commands and limits.

- **P2-06.2 complete:** `src/research_platform/search/lexical_analyzer.py` and
  nine focused tests define scientific-en-v1. It keeps stopwords, no stemming,
  one-character terms, acronyms, numeric/compound aliases and scientific operators;
  normalization is Unicode NFC/casefold plus common dash/minus and micro-symbol
  mapping. The corpus comparison measured 1,917,082 tokens/65,432 vocabulary terms
  (2.012 s) versus BM25S defaults at 1,345,214/43,469 (0.511 s). All ten designed
  diagnostic features survive, compared with one under the default tokenizer. This
  is token-retention evidence, not a quality result. Ruff, format, mypy and all nine
  focused tests pass; see `docs/reference/phase-2-bm25s-analyzer.md`.
- **P2-06.3 complete:** `search/lexical.py` builds separate stable-row evidence and
  paper indexes, bound to the exact profile and snapshot selection. The read-only
  loader verifies exact selected chunk IDs, both permission records, and source PDF
  checksums in one repeatable-read transaction; draft loading requires explicit
  evaluation access. Row maps contain no source text, keep duplicate content under
  distinct IDs, and account for missing/empty paper fields. OpenAlex abstract
  reconstruction is shared with manifest export. BM25S 0.3.11 is declared in
  `pyproject.toml` and `environment.yaml`; `requirements-bm25s.txt` pins the verified
  wheel hash for CI/Docker installation alongside the Conda-only explicit lock.
- **P2-06.4 complete:** `LexicalRetriever` applies the resolved eligible IDs before
  top-k, discards zero scores and deterministically sorts ties. It handles empty
  eligibility, empty analyzer output and zero matches; unknown IDs fail closed. A
  three-document independent Okapi score/order example and restrictive singleton
  scope pass.
- **P2-06.5 complete:** `search/lexical_artifacts.py` publishes immutable
  content-addressed BM25 arrays and sidecars by atomic directory rename, without
  storing a text corpus. Load checks expected profile, exact snapshot/status, analyzer,
  scoring settings, row-map identity and all file checksums; draft loads require
  explicit evaluation access. Identical rebuilds reuse a verified artifact and report
  storage use. The `index lexical-build` command
  reads without applying migrations; `index lexical-query` uses `LexicalRetriever`,
  the same module planned for API search. Eleven lexical tests and fifteen OpenAlex
  tests pass (26 focused tests total), covering save/load, tamper, rebuild, draft
  access and a synthetic CLI query;
  Ruff, format and source mypy pass. The DB loader integration assertion was added
  but not run because dedicated PostgreSQL/Qdrant URLs are not configured.
- **P2-06 accepted for implementation:** [ADR-0010](../adr/0010-phase2-bm25s-lexical-index.md)
  records BM25S 0.3.11 and scientific-en-v1 as a reversible Phase 2 choice, not the
  final retrieval default. No profile-compatible artifact was published from the
  accepted review DB because it is not migrated to 015; the CLI never migrates it.
- **P2-07.1 complete; assistant-reviewed:** `SnapshotDenseSearch.search_query` and
  `evaluate_query` reuse E5-small-v2's pinned query adapter and required prefix.
  Candidate limit, exact profile/configuration identity and E5 model, revision,
  preprocessing, dimensions, distance and token limit are checked before embedding
  or Qdrant access. Query vectors must contain 384 finite values and have unit L2
  norm. Ranked matches are hydrated before the profile lease ends through the exact
  selected chunk relation; the loader rechecks snapshot identity and both storage/
  indexing permission records and returns source text and lineage from PostgreSQL.
  Draft hydration requires the explicit evaluation path. Focused dense/index tests
  pass (19); full non-integration tests pass (256). Ruff, format and source mypy
  pass. A live database hydration assertion was added but not run because the
  dedicated PostgreSQL/Qdrant URLs are not configured.

- **P2-07.2 complete; assistant-reviewed 2026-09-26:** pinned BGE-base-en-v1.5
  was run on CPU and the RTX 3050 using the same 12 local chunks (four prose, four
  pipe-table-like, four near the accepted input maximum). At batch size 4 and five
  warm repetitions, the GPU completed the longest group at 0.141 s per four chunks;
  allocator peak was 490 MiB allocated / 574 MiB reserved. CPU peak RSS was 1.34 GiB.
  The Windows host driver is exposed to WSL; `nvidia-smi` inside the project WSL
  environment reports host driver 617.14, and its normal PyTorch `2.14.0+cu130`
  build detects the GPU. Final GPU measurements were rerun in that WSL environment.
  An isolated CUDA 12.6 wheel used for an earlier exploratory run
  was removed. Project dependencies remain unchanged. This establishes feasibility,
  not retrieval quality or full-index cost.
- **P2-07.3 complete; assistant-reviewed 2026-09-26:** exact pinned tokenizers
  audited all 44,277 unique accepted chunks and the E5 `passage: ` prefix. No chunk
  exceeds 512 tokens under either candidate (E5 max 485; BGE max 483), so the exact
  accepted selection is a common-compatible set. Sorted chunk-ID digest:
  `823bd7cd64ed89f555add9ec4967777118b8c1845b4b949e260f88987c9016f8`. Raw IDs
  and counts remain private under ignored local-reference.
  See `docs/research/phase-2-bge-base-en-v1-5-pilot-research.md`.
- **P2-07.4 complete; assistant-reviewed 2026-09-26:** the pinned BGE embedder is
  selected from a separately versioned configuration at
  `configs/phase2-bge-base-en-v1-5-index.example.json`; its configuration ID is
  `sha256:c90fc73b817284ab9a7b6efd6168b06cd560247934da9e7b014c68317f562735`.
  Synthetic lifecycle coverage
  verifies a distinct 768-dimensional Qdrant collection, exact selected-ID
  reconciliation/readiness digests, matching configuration payloads, known-neighbor
  ranking, reload through a new index object, and two successful rebuilds. The E5
  384-dimensional collection remains unchanged. Focused dense hydration tests cover
  BGE and reject an unreviewed model revision. `pytest -m 'not integration' -q` passes
  (263 passed, 19 deselected); `ruff check .`, `ruff format --check .`, and `mypy src`
  pass. BM25S was supplied only through a `/tmp` verification path. No accepted-corpus
  index was built.

- **P2-07.5 complete; assistant-reviewed 2026-09-26:** dense retrieval applies
  inclusive year ranges and OR-within-field metadata predicates before top-k. Rebuilds
  populate a versioned payload marker and indexed metadata, reconcile exact Qdrant
  payloads against the selected DB inputs, and publish readiness only on a full match.
  Hydration rechecks the shared filter contract against source-authoritative metadata;
  stale filter payloads require rebuild. Both E5 and BGE have known-neighbor filter
  tests. Shared checks pass (270 passed, 19 deselected; Ruff, format and mypy). The
  accepted DB remains unmigrated to 015, so no accepted-index backfill was run.
- **P2-08.1–08.2 complete; assistant-reviewed 2026-09-26:**
  `search/fusion.py` implements reciprocal-rank fusion over lexical and hydrated dense
  evidence candidates. Lexical positions and dense ranks are 1-based; duplicate IDs
  within a branch fail, shared IDs receive both terms, and equal fused scores sort by
  stable evidence ID. Results preserve each raw branch rank/score and the fused rank/
  score. The profile records method `rrf-v1` and a positive rank constant (development
  default 60; not selected as the final value). Five focused fusion tests cover the
  hand-computed sum, overlap, disjoint and empty branches, missing-component
  provenance, duplicate IDs and stable ties. Full non-integration checks pass
  (276 passed, 19 deselected), as do Ruff, formatting and strict source mypy.
  The first test collection lacked `bm25s` in the existing Conda environment; rerunning
  with the cached `/tmp` verification dependency path passed without modifying that
  environment. An initial mypy loop-variable collision was fixed and the rerun passed.
  At that checkpoint, pool bounds, caller-level profile enforcement, shared filters
  and branch failure semantics were still unfinished under P2-08.3–08.5.
- **P2-08.3 complete; assistant-reviewed 2026-09-26:** `HybridEvidenceSearch`
  runs lexical and dense branches with the profile's lexical/dense limits, then applies
  its fused-union cap. It rejects paper indexes, draft indexes on serving calls,
  unsupported stages, active filters until P2-08.4, and any lexical or dense response
  whose profile, snapshot, index configuration or limit differs. Lexical reports the
  exact count of positive matches; the unfiltered dense branch reports the exact
  snapshot index count. Each pool records its limit, available/observed count, returned
  count and truncation; a fused-union count is marked as a lower bound when an upstream
  branch was itself truncated. The response records applied filters (empty in this
  substep). Focused hybrid/dense/lexical/fusion checks pass (38); full non-integration
  suite passes (281 passed, 19 deselected), with Ruff, format and strict source mypy.
  At that checkpoint filtered counts and hybrid filters were still open; structured
  branch failures remain for P2-08.5.
- **P2-08.4 complete; assistant-reviewed 2026-09-27:** lexical row-map format/schema
  moved to v2 and now carries source-loaded publication year, evidence kind and
  document-version kind. The exact version is part of the lexical profile identity;
  previously built v1 lexical artifacts must be rebuilt. Lexical filtering uses the
  shared `SearchFilters` contract before candidate slicing and fails closed on missing
  values. Dense search sends the same payload conditions before Qdrant top-k and uses
  Qdrant's exact filtered count endpoint for candidate totals and truncation
  ([API reference](https://api.qdrant.tech/api-reference/points/count-points)). The
  hybrid response verifies both branches applied the requested filters and records
  them. Tests cover all filter fields, eligible results below an unfiltered top-1,
  empty eligibility and absent metadata. Full non-integration suite passes (286 passed,
  19 deselected); Ruff, format and strict source mypy pass. Initial focused checks found
  a missing lexical helper and a duplicate count-method definition; both were repaired
  before the passing rerun. The DB-backed lexical-loader assertion was added but not
  run because dedicated PostgreSQL/Qdrant URLs are unavailable. The accepted review DB
  and its indexes remain untouched.
- **P2-08.5 complete; assistant-reviewed 2026-09-27:** `HybridSearchFailure`
  provides a structured stage (`lexical`, `dense` or `fusion`), requested mode, null
  effective mode, profile/snapshot IDs and error class. Its serialized message is safe
  and generic; the original exception remains chained for internal diagnostics. A
  failed requested branch or fusion stage yields no partial candidates, and no degraded
  single-branch path is enabled. Seven focused hybrid tests pass, including lexical and
  dense failures with no successful partial result. Full non-integration suite passes
  (288 passed, 19 deselected), with Ruff, formatting and strict source mypy. P2-08's
  Done condition is met; P2-09.1 is next.

**P2-09.1 implementation complete; assistant-reviewed 2026-09-27:**
`search/paper_reads.py` resolves canonical OpenAlex IDs through both stored identity paths
in one SQL query with a two-row resolution cap. It distinguishes unknown IDs from known
papers outside the requested snapshot, returns selected document ID/version/kind only
for members, and reports title/abstract/year availability. The query projects only the
abstract index needed for that flag and reads no evidence/chunk text or live OpenAlex
data. Six unit cases cover selected, outside, unknown, missing snapshot, conflicting
identity, query bounds and invalid public IDs. A PostgreSQL integration case exercises
canonical and identifier-table resolution, but was skipped because
`RESEARCH_PLATFORM_TEST_DATABASE_URL` is not configured. The full non-integration suite
passes (294 passed, 20 deselected); Ruff, format and strict source mypy pass.
`PaperMetadataResponse`/HTTP routing remain scheduled under P2-16.

**P2-09.2 complete; assistant-reviewed 2026-09-27:**
`search/paper_grouping.py` converts ranked, filter-eligible `EvidenceHit` values into
one paper result each. Paper order follows each paper's strongest hit rank, with
public paper ID as a stable tie break. The selected hit's component ranks/scores are
copied intact; scores across chunks are never summed or averaged. Supporting hits
are distinct by chunk ID and capped by the retrieval profile's
`paper_support_limit` (three by default). Duplicate chunk IDs fail closed. Six
focused tests cover long-paper score bias, support caps, stable ties, duplicates and
empty input. Full non-integration suite passes (300 passed, 20 deselected); Ruff,
format and strict source mypy pass.

**P2-09.3 complete; assistant-reviewed 2026-09-27:**
`search/paper_fusion.py` combines metadata `PaperMetadataHit` rankings with grouped
evidence `PaperHit` rankings using profile-bound `rrf-v1` and its rank constant. It
adds one reciprocal-rank contribution per available branch, never adds the raw
metadata and passage scores, and sorts fused ties by public paper ID. Results retain
`metadata_rank` and `evidence_rank`; evidence passage scores remain on their
supporting hits, while the top-level fusion component records the combined score.
Metadata-only hits keep an empty evidence tuple. The initial rule and limitations
are documented in `docs/reference/phase-2-paper-fusion.md`; rank constant remains
provisional for P2-14. Seven focused tests cover overlap, disjoint candidates, raw
score separation, metadata-only results, deterministic ties, and invalid duplicate
IDs/ranks; typed response serialization preserves branch ranks. Full non-integration
suite passes (307 passed, 20 deselected); Ruff, format and strict source mypy pass.

**P2-09.4 complete; assistant-reviewed 2026-09-27:**
`search/paper_selection.py` derives the maximum paper-candidate union from the
profile metadata/evidence stage caps (each stage remains at or below the existing
200-candidate maximum), rejects an over-cap or duplicate-paper list, and selects a
bounded requested page. `PaperResultSelection` reports truncation, observed
`omitted_count`, and whether that count is exact. If an upstream pool was truncated,
the result remains truncated even when underfilled and warns that omitted count
covers only observed candidates. Six tests cover profile-derived bounds, exact page
omissions, upstream lower-bound semantics, cap/uniqueness failures and contract
consistency. Full non-integration suite passes (313 passed, 20 deselected); Ruff,
format and strict source mypy pass.

**P2-09.5 complete; assistant-reviewed 2026-09-27:**
`search/paper_graph.py` reads one hop from stored `citations` and
`unresolved_citations` rows in a read-only repeatable-read transaction. The source
and resolved endpoints are classified as in-snapshot or outside-snapshot; only
stored title/year metadata is returned, with no document or passage text.
Unresolved endpoints return their namespace and identifier without an invented
title. References and incoming citations use a direction-bound keyset cursor over
endpoint kind, canonical public ID and edge source; page size is capped at 100. The
response states that incoming citations cover only the locally observed graph. Five
unit tests pass for directions, cursor pagination, source/endpoint scope, unresolved
IDs and invalid cursors. PostgreSQL integration fixtures for paper reads and graph
reads were added but both skipped because `RESEARCH_PLATFORM_TEST_DATABASE_URL`
is not configured. Full non-integration suite passes (318 passed, 21 deselected);
Ruff, format and strict source mypy pass. P2-09 Done behavior is covered offline;
database-backed SQL execution remains an environment-gated check.

**P2-10.1 complete; assistant-reviewed 2026-09-27:** the primary-source audit
and bounded MiniLM/BGE resource pilot are recorded in
docs/research/phase-2-reranker-candidate-research.md. Both pinned candidates ran
on CPU and the WSL RTX 3050 at FP32/batch 4 using identical development-only pairs;
all outputs were finite/aligned, including a 512-token pair, with no OOM. The report
records revisions, model-declared licenses, pair limits, CPU/GPU latency and memory.
This is feasibility evidence only; quality and final reranker choice remain OPEN.
The WSL process sees the Windows host driver (617.14), rather than a separately
installed Linux driver. No project dependency, index or database changed.

**P2-10.2 complete; assistant-reviewed 2026-09-27:** pair format
query-source-chunk-v1 passes each query and complete source chunk unchanged, keeps
the full EvidenceHit and its source/rank/component provenance, and adds no metadata
context. Every model tokenizer counts the complete pair with truncation disabled.
An over-budget candidate for any comparison tokenizer fails the entire pair set;
no evidence is cut or dropped. Table row-group text preserves its ingested caption,
units, header associations, footnotes where present and cell values; oversized-cell
units also retain coordinates. Tests cover
table associations, stable source alignment, token limits and failure behavior.
Full non-integration suite passes (332 passed, 21 deselected); Ruff, format and
strict source mypy pass. Quality remains unmeasured.

**P2-10.3 complete; assistant-reviewed 2026-09-27:**
`src/research_platform/search/reranker.py` adds a profile-bound scoring adapter
with a dedicated single-worker executor, bounded batches, an inference timeout,
finite raw-score and exact per-batch alignment checks, and deterministic score ties
by original fused rank. It rejects candidate counts above either configured bound
and returns no partial results after any batch failure. Score records retain the exact RerankerIdentity and original EvidenceHit.
`tests/test_reranker.py` uses fake scorers
and token counters to exercise worker-thread execution, batching, identity, ties,
limits, timeout, over-budget pairs, malformed outputs and partial-batch failure.
The focused reranker and pair suites pass (24 tests). The full offline suite passes
(342 passed, 21 deselected) using the existing temporary BM25S verification path;
full Ruff and formatting pass (158 files), strict mypy passes (67 source files), and
`git diff --check` passes. Timeout cannot stop an already-running Python inference
thread; the adapter serializes later requests behind that worker. P2-10.5 wires the
caller-visible fallback. No model weights or project dependencies changed.

**P2-10.4 complete; assistant-reviewed 2026-09-27:**
`src/research_platform/search/reranker_results.py` maps scores back onto only the
exact supplied candidate pool. It requires the selected hybrid profile, matching
reranker, retrieval-profile and query-hash identities, complete one-to-one candidate
coverage, unchanged source hits, and retained original fused ranks. It assigns the reranker rank/score while keeping
lexical, dense and fusion components unchanged. It rejects injected, lost, duplicated,
modified or already-reranked evidence. Fake-boundary tests cover provenance retention,
pool substitution/omission, missing fused-rank metadata, query/profile identity
mismatch and reranker mismatch; focused suite passes (28 tests). Full offline suite:
346 passed, 21 deselected using the existing temporary BM25S verification path. Full
Ruff check/format pass (159 files), strict mypy passes (68 source files), and
`git diff --check` passes.

**P2-10.5 complete; assistant-reviewed 2026-09-27:**
`src/research_platform/search/reranker_models.py` adds local-only, FP32 loaders for
the exact MiniLM and BGE revisions reviewed in 10.1. It loads fast tokenizers and
Sentence Transformers `CrossEncoder` with `local_files_only=True` and
`trust_remote_code=False`; prediction explicitly uses identity activation and no
softmax so scores remain raw. Device unavailability, allocation exhaustion, missing
weights/runtime, inference timeout, invalid output, incomplete batches and pair
overflow have controlled error types. `reranker_service.py` returns the original
candidate tuple and safe fallback details naming model, revision and error type; it
omits query, evidence and backend exception text. Fake tests cover these failures and
success. A local-only CUDA smoke and profile-bound full adapter/provenance smoke both
passed for each pinned model using one synthetic pair (19 tokens) in WSL; the GPU was
the RTX 3050, with the Windows host driver exposed as 617.14. No corpus text was used
in these smokes, no weights were downloaded, and no dependency changed. Full offline
suite: 355 passed, 21 deselected using the existing temporary BM25S verification
path; full Ruff and format pass (162 files), strict mypy passes (70 source files), and
`git diff --check` passes. Retrieval quality remains unmeasured and model selection
remains OPEN.

**P2-11.1 complete; assistant-reviewed 2026-09-27:** conservative evidence
deduplication is implemented in `src/research_platform/search/evidence_deduplication.py`.
Exact chunk repeats require a consistent source payload; source-overlap removal
requires complete resolved coverage in the same document/extraction. Text spans,
table body rows and oversized-cell token intervals use separate half-open coordinate
spaces. Repeated table headers do not count as content; partial spans, unresolved IDs,
and similar wording across papers remain. Omission records resolve to retained hits.
The policy is in `docs/reference/phase-2-evidence-deduplication.md`; 15 focused
synthetic tests pass, including cross-paper, containment, partial-overlap, unresolved
lineage and table-header cases. The offline suite reports 371 passed / 21 deselected;
Ruff check and format pass (165 files), strict mypy passes (71 source files), and
`git diff --check` passes. Continue with P2-11.2 (configurable per-paper bounds).

**P2-11.2 complete; assistant-reviewed 2026-09-27:** `search/evidence_selection.py`
applies the profile's `evidence_per_paper_limit` (default 3, maximum 5) independently
per paper, retaining global rank order and original scores/ranks. Omission records
retain chunk IDs, paper IDs, ranks and source evidence IDs. This cap is separately
profile-bound from `paper_support_limit`, which controls passages attached to
paper-level results. The API/search contract and
`docs/reference/phase-2-evidence-selection.md` describe both bounds. Eighteen
focused selection/profile/grouping tests pass. The offline suite reports 377 passed /
21 deselected; Ruff check and format pass (168 files), strict mypy passes (72 source
files), and `git diff --check` passes. The default remains provisional pending P2-14.
Continue with P2-11.3.

**P2-11.3 complete; assistant-reviewed 2026-09-27:** table hits can be enriched
with structured context in `search/table_context.py`, resolved through exact source
unit IDs and the selected extraction/table. Row groups carry complete selected rows
and header matrices; oversized-cell hits carry only their exact value segment and
referenced headers. Both preserve caption, units, footnotes, cell coordinates,
merged ranges, and source evidence IDs. `EvidenceHit.text` remains unchanged as the
bounded indexed-chunk rendering. The typed HTTP evidence model exposes the optional
context; unresolved or inconsistent provenance fails closed. Eight focused table
context tests pass. The offline suite reports 385 passed / 21 deselected; Ruff check
and format pass (171 files), strict mypy passes (73 source files), and
`git diff --check` passes. See
`docs/reference/phase-2-table-evidence-context.md`. Continue with P2-11.4.

**P2-11.4 complete; assistant-reviewed 2026-09-27:** `search/evidence_budgets.py`
bounds evidence pages by the requested item count, profile per-paper limit, and
profile character/token budgets. A second helper applies one shared budget to all
supporting passages in a paper-result page without changing paper rows, scores or
ranks. It counts hit text and every structured table string using the versioned
`unicode-token-v1` policy. Whole evidence units are kept intact or omitted with
chunk/source IDs and each exceeded reason; upstream-pool truncation makes omitted
counts explicitly inexact. Defaults are 12,000 characters / 4,000 tokens, maxima
24,000 / 8,000, all profile-bound under schema 2. Nine focused budget cases pass.
The offline suite reports 394 passed / 21 deselected; Ruff check and format pass
(174 files), strict mypy passes (74 source files), and `git diff --check` passes.
See `docs/reference/phase-2-evidence-result-budgets.md`. P2-11.5 is complete below.

The roadmap owns the task status table. For each completed substep record changed
paths, actual commands/results, code/config/benchmark IDs and any limitations.
Mark a task complete only when its Done condition is met; update this file's next
step without duplicating the full checklist. Preserve intermediate failures and
assistant-review uncertainty. Thresholds are frozen before held-out assessment.

A failed measurement or missing external input is not completion. Continue useful
independent work and report the specific blocker. Any source/schema/permission
change follows the source-of-truth change-control rule. Keep the original corpus
usable throughout.

**Next step:** P2-12.1. Freeze the larger benchmark sampling plan after recording
calibration review effort and coverage.
P2-09 is complete; run its PostgreSQL integration fixtures when the dedicated
research_test database is configured. Keep the accepted
review DB read-only until its migration/readiness gate is met.


**P2-11.5 complete; assistant-reviewed 2026-09-27:** `SearchResponse` now reports
exact `eligible_count`, a derived status (`no_eligible_records`,
`no_candidates_returned`, or `ranked_candidates`), and `ranking_interpretation:
ranking_only`. Lexical counts eligible rows separately from positive term matches;
dense reports its exact snapshot/filter count; hybrid rejects branch eligibility
mismatches. Successful evaluation attempts persist the same semantics in run schema
2. No answerability or claim-support inference and no relevance cutoff are exposed.
The offline suite passed 396 tests with 21 deselected; Ruff check passed, formatting
passed for 176 files, strict mypy passed for 74 source files, and `git diff --check`
passed; `pip check` found no broken requirements. See `docs/reference/phase-2-search-result-semantics.md` and ADR-0011.
