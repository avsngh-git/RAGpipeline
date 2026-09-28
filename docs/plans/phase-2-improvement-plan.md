# Phase 2 — Completion review and improvement plan

Reviewed 2026-09-28 by the assistant against HEAD `ed56e59` **plus the existing
uncommitted implementation/configuration changes**. This is a repair plan for the
approved Phase 2 scope, not Phase 3 approval. The [source of truth](../agents/scientific-research-platform-source-of-truth.md)
remains authoritative; the [roadmap](phase-2-retrieval-evaluation.md) owns phase
completion and the [evaluation protocol](phase-2-evaluation-protocol.md) owns scoring.

## Assessment

The retrieval implementation is substantial and works on real local data. Preserve
its lexical/dense/hybrid/reranked services, provenance, table handling and exact
snapshot boundaries. The immediate need is reliable acceptance and reproducibility,
not a larger model or another ranking-parameter search.

The latest published assessment missed warm p95: **1,602.2 ms versus 1,500 ms**.
That 1,500 ms value was the prior acceptance gate, not a request timeout. Per the
owner’s 2026-09-28 direction, a fresh R8 assessment will use a 2,000 ms maximum warm
p95; the independent per-request deadline remains 30 seconds. Historical results keep
the limits against which they were originally scored.
There is a concrete source of avoidable overhead: hybrid requests reconstruct the
entire 44,277-chunk selection three times. Readiness checks, dense-hit hydration and
fused-hit hydration each repeat that work. A measured diagnostic found an average
**682.68 ms/request** inside these three reconstructions. Start with request-scoped
reuse under the existing database lease, preserving all integrity checks.

The held-out report also miscounts its gates: its table and `acceptance-v8.toml`
define nine quality/source gates and five operational gates, **14 total, with 13
passing and one failing**. The repeated “14/15” summary needs reconciliation; it
must not become an extra undocumented criterion or a claim of acceptance.

## Verified evidence and limits

| Check in this review | Result |
| --- | --- |
| Offline pytest | 424 passed; 21 integration tests deselected |
| Ruff lint / formatting | Pass; 200 files formatted |
| Strict mypy | Pass; 79 source files |
| Real-model runtime, current v8 profile | Started successfully with existing offline caches |
| Synthetic warm probe | 18 measured requests after six warm-ups; median 1,078.83 ms, nearest-rank p95 1,340.61 ms |
| Instrumented repeat of that probe | 18 measured requests; median 1,121.53 ms, p95 1,381.18 ms |
| Embedding cancellation probe | Eight concurrent fake encoder workers started; all eight were still running immediately after their awaiting requests were cancelled |

The synthetic probe used three invented queries, each on paper and evidence search:
“retrieval augmented generation evaluation”, “comparison of dense and lexical
retrieval methods”, and “retrieval accuracy benchmark results” with the table-row-group
filter. It used result limit 10 and the actual executor, PostgreSQL, Qdrant and cached
CUDA models. It did **not** include HTTP serialization, quality judgments, a balanced
development sample or a sufficient tail-latency sample. All measured responses retained
reranked mode. These timings diagnose costs; they neither reproduce the held-out tail
nor prove the acceptance gate now passes.

Instrumented durations below are means over those 18 requests. Hydration includes
selection reconstruction; **do not add that row to the reconstruction row**.

| Component | Calls/request | Mean ms/request |
| --- | ---: | ---: |
| Exact selection reconstruction | 3 | 682.68 |
| Authoritative eligibility query | 1 | 149.31 |
| Query embedding | 1 | 11.90 |
| Reranker | 1 | 137.44 |
| Table-context attachment | 1 | 17.09 |
| Hydration, inclusive of repeated selection work | 2 | 481.46 |

Local diagnostic scripts and output are retained under
`local-reference/phase2-runs/progress-review-20260928/`. Run them from the repository:

```bash
conda run --no-capture-output -n sci_research_agent python local-reference/phase2-runs/progress-review-20260928/baseline-probe.py
conda run --no-capture-output -n sci_research_agent python local-reference/phase2-runs/progress-review-20260928/instrumented-probe.py
```

These are inspection scripts, not a supported benchmark interface. They temporarily
wrap methods only in their own process and do not modify application source. Their
cache paths are machine-specific: this review used `/tmp/phase1-embedding-hf-cache`
and `/tmp/phase2-reranker-hf-cache`. The runbook's `local-reference/phase2-model-cache`
and `local-reference/phase2-reranker-cache` paths were absent. R2 replaces this local
knowledge with a reusable command; R7 addresses durable cache configuration.

No held-out questions, rankings, labels or origin ledgers were opened. No corpus,
index, model, threshold or ranking behavior was changed. Live integration, a new
Docker build, dependency audit and hosted CI were not rerun in this review; earlier
claims for them remain historical evidence until checked on the final revision.

## Execution order

Execute R1 → R2 → R3 → R4 → R5 → R6 → R7 → R8. Each step has a completion test.
R6's representation experiment is conditional. Keep fixes reviewable and record
actual commands/results in the phase handoff. All new judgments are assistant-reviewed.

### R1 — Protect the current behavior before optimizing

**Files:** `tests/test_profile_manifest.py`, `tests/test_reranker.py`,
`tests/test_paper_selection.py`; a new executor-composition test module as needed.

1. Test the **active v8** manifest and its bound acceptance file. Current frozen-profile
   tests target v1, whose rerank cap is 50. Keep historical fixture tests, but add an
   assertion that the runtime-selected manifest is tested and packaged.
2. Exercise `rerank_with_fallback` with a full pool larger than the rerank prefix:
   only the prefix gets model scores; its order changes deterministically; the tail
   retains order, identities and original component provenance; visible ranks remain
   unique. Cover empty/short pools, cap boundaries and ties.
3. Force overflow, timeout and a later-batch failure within the prefix. Require the
   complete original hybrid pool on fallback, with its actual effective profile/mode.
   An oversized tail item must not be scored or cause prefix fallback.
4. Test paper selection with `rerank_top_k < fused_top_k`. The scan bound must cover
   the metadata/evidence union, including tail-derived papers. Preserve strongest-hit
   grouping; do not sum passage scores to improve paper metrics.
5. Add a model-free test through the actual `Phase2SearchExecutor`, using dependency
   fakes. Cover paper/evidence selection, table context, fallback and incompatible
   profiles. Current API tests largely inject a finished service; component tests do
   not verify this entire composition. Document which fusion configuration governs
   upstream evidence versus final paper fusion and assert that actual distinction.

**Done:** the new tests run on CPU with no downloads and would catch loss of the
hybrid tail, incorrect paper scan bounds or a stale runtime profile. Full small checks pass.

### R2 — Establish a development-only performance loop

**Files:** a tracked diagnostic command under `scripts/` or the existing CLI;
shared runtime/evaluation services; `docs/operations/phase-2-search.md`.

1. Turn the useful parts of the local probes into a parameterized, tracked command.
   Accept explicit database, Qdrant, cache, profile and development-input paths.
   Reuse production retrieval; keep private inputs/output outside Git. Validate a
   development allowlist and reject spent/test inputs. Exclude q20/q21 and follow the
   existing split policy; never read `*origins.json`.
2. Time eligibility, exact selection validation, embedding, Qdrant, hydration,
   reranking, table context, selection and HTTP serialization separately. Emit counts
   and durations without query text, evidence IDs or passages in ordinary logs.
   Separate inclusive timings from exclusive timings.
3. Run a fixed, development-only mixture of both endpoints, prose/tables, restrictive
   filters and zero eligibility. Declare result limits, warm-up, order seed, device,
   threads, concurrency, background load and repetitions before comparing versions.
4. Use at least 100 warm requests per run, repeated across three sessions. Report
   medians/p95 and fallback/failure counts; retain slow requests and failures.
   Keep a shorter synthetic probe for quick diagnosis. Measure limit-10 interaction
   separately from any deeper quality-evaluation requests.
5. Save a before-change baseline and fingerprints of ordered results and effective
   modes for later differential comparison. Record code/worktree and configuration IDs.

**Done:** one documented command reproduces stage costs and warm latency from a fresh
checkout with supplied local assets. No held-out information enters this loop.

### R3 — Validate the exact selection once per retrieval operation

**Files:** `ingestion/indexing.py`, `search/dense_search.py`,
`search/hybrid_search.py`, `search/application.py` and relevant integration tests.

1. Preserve `_ready_index_lease`'s shared advisory lock, snapshot row lock, exact
   selection comparison, configuration/readiness checks and cancellation cleanup.
   Extend the scoped repository interface to carry the already-validated selection
   and an immutable membership set of selected chunk IDs on its owned connection.
2. Pass this repository-created context through dense retrieval and both hydration
   calls. Membership tests reuse the set; hydration still queries authoritative rows
   and checks document/extraction lineage, permissions and filters. Do not expose a
   caller-controlled `skip_validation` flag.
3. Keep standalone search/hydration safe: callers without a context acquire and
   validate their own scope. Draft evaluation retains its explicit separate path;
   no context or cached membership survives a request. Avoid nested read leases,
   which the existing repository rejects, and avoid holding extra pool connections.
4. Restructure the hybrid executor so the context covers vector retrieval and final
   candidate hydration. Release the lease once authoritative candidate material is
   ready, before expensive reranking where possible. This may require separating
   candidate acquisition from reranking inside `_evidence_candidates`.
5. Add synthetic integration regressions for concurrent rebuild exclusion, draft
   isolation, stale configuration/selection, out-of-snapshot IDs, permission denial,
   cancellation and connection reuse. Verify permissions again on subsequent requests;
   a finalized snapshot does not freeze permission evidence.
6. Replay R2 with the exact same ranking/profile settings. Compare ordered hits,
   source references, component scores, warnings and effective modes. Expect one
   selection reconstruction per hybrid request instead of three. Measure the actual
   saving; 682.68 ms is the observed total cost, not a guaranteed saving.
7. Only if necessary, profile the remaining eligibility SQL with read-only query
   plans. Preserve exact filtered eligibility and pre-top-k filtering. Consider
   eliminating duplicate hydration after proving permission/filter equivalence.
   Leave global caches, schema changes and parallel model execution out of this first fix.

**Done:** unchanged retrieval behavior on the development comparisons, integrity
regressions pass, and repeated performance runs meet the then-current 1,500 ms
engineering target. The R6 development runs met it. The fresh held-out R8 gate is the
owner-approved 2,000 ms maximum in acceptance-v10; 1,200 ms remains optional engineering
headroom, not an acceptance threshold. Use measured residual stage cost for any next
bounded change.

### R4 — Bound embedding work after request cancellation

**Files:** `ingestion/embeddings.py`, runtime lifecycle, embedding/API tests.

1. Add a regression at `embed_query` with a controllable blocking encoder. Cancel or
   time out its awaiting request, then submit more requests. The current implementation
   uses the default `asyncio.to_thread` executor, with no adapter-level admission bound;
   the review reproduced eight workers continuing after eight request cancellations.
2. Give query inference a bounded worker/admission policy, following the reranker's
   existing pattern. Busy requests should fail safely or use a bounded queue with a
   deadline. Do not release capacity merely because the awaiting coroutine cancelled;
   the actual worker must finish first.
3. Preserve batch ingestion behavior and model-load safety. Provide lifecycle cleanup
   and safe timeout/busy error mapping. A semaphore released on coroutine cancellation
   alone does not solve work continuing in its thread.
4. Exercise repeated cancellation, slow model load, success after a worker finishes,
   and concurrent readiness/search. Record active/queued work bounds explicitly.

**Done:** deterministic tests prove bounded outstanding inference after cancellations;
no silent retrieval fallback is introduced. This closes the P2-17 execution-bound gap.

### R5 — Make acceptance accounting reproducible and accurate

**Files:** `evaluation/run_records.py`, `evaluation/runner.py`, a tracked acceptance
runner/report generator, acceptance tests and the sanitized report.

1. Implement a checked gate mapping for the frozen TOML. Generate the gate table and
   pass/total summary from the same evaluated records. Missing, non-finite or unknown
   metric/gate inputs fail explicitly. Reconcile the current 13/14 versus 14/15 error
   without changing any limit or reading private item-level outcomes.
2. Separate expected selection diagnostics from execution degradation.
   `successful_search_attempt` currently labels any warning as degraded, including
   routine pool truncation. Introduce typed reasons/status fields; preserve warnings,
   truncation and omissions independently. Version serialized records if needed.
3. Count fallback separately from hard failure and clean execution. Report requested
   and effective configuration/mode. The current selected aggregate includes four
   fallback requests out of twenty: it describes the deployed fallback policy, not
   twenty successful cross-encoder executions. Preserve that distinction in quality
   summaries and denominators, rather than silently removing difficult requests.
4. Test hand-computed success/truncation/fallback/timeout examples, report arithmetic,
   nearest-rank p95, undefined denominators and invalid inputs. Preserve the scoring
   protocol; any metric interpretation correction must be versioned and disclosed.
5. Move reusable benchmark execution, bootstrap and report logic out of ignored
   one-off scripts. Keep private datasets outside Git and load them by explicit paths
   and hashes. Provide a tiny synthetic replay fixture through the same command.
6. Preserve historical results. Reconcile summaries in the report, roadmap, handoff
   and source of truth after verifying the mapping; do not rewrite an old failure
   into a pass. Do not use corrected reporting as permission to reuse spent families.

**Done:** a fresh checkout can reproduce synthetic evaluation and generate internally
consistent tables. Real evaluation requires local assets, not an untracked algorithm.

### R6 — Diagnose fallback without starting another tuning loop

**Files:** development diagnostic outputs and reranker pair-format documentation;
only change model input code if development evidence warrants it.

1. Collect typed fallback causes on allowed development queries: pair overflow,
   inference timeout, busy worker, device exhaustion and other adapter failures.
   Break down by input length and prose/table kind without exposing source text.
2. If fallback stays within the frozen allowance and quality gates are met, retain
   the current whole-pool policy. The published 20% rate passes its 35% gate; reducing
   it is not a prerequisite invented by this review.
3. If overflow blocks development usefulness, design a separate bounded experiment:
   preserve query budget and meaningful, source-linked prose/table units; version the
   pair formatting and affected profile. No silent truncation, missing table headers
   or mixing incomparable partial reranker scores with the unscored tail.
4. Compare the proposed representation on the same development judgments and saved
   candidate pools. Retain the simpler existing policy if the experiment does not
   demonstrate an improvement. Record the outcome before another freeze.

**Done:** fallback causes and limitations are explained; any representation change has
independent development evidence. No further cap/RRF changes are made merely to seek
a passing held-out result.

### R7 — Make operation and handoff reproducible

1. Establish one explicit active-profile reference shared by runtime, CLI, packaging
   and tests. The runtime currently hardcodes v8 while manifest tests use v1; retain
   historical manifests but test the actual selected reference and dependencies.
2. Document durable model-cache provisioning and offline reload. Parameterize the
   actual paths instead of relying on `/tmp` surviving. Verify startup, readiness,
   both endpoints and absence of implicit downloads using supplied local assets.
3. Keep the handoff's current status, next task and blockers concise. Move historical
   step narratives behind an archive link while retaining their evidence. Resolve
   stale contradictory instructions such as “continue P2-06” amid completed tasks.
4. Measure retained lexical/model/Qdrant disk footprint and identify disposable
   experiment assets. Report first; preserve accepted indexes and referenced variants.
5. Run lint, format, mypy, offline tests, fresh disposable integration, dependency
   consistency/audit, Docker build and runtime smoke. Reuse existing checks; do not
   run integration tests against the accepted database.
6. Follow the existing publication workflow. Record the exact code/config revision
   and successful hosted CI for it. Preserve unrelated worktree changes; inspect the
   untracked `NUL` artifact before deciding whether it belongs in any change set.

**Done:** local startup/replay instructions work, current-profile tests pass, and
P2-19 has evidence for the actual revision intended for acceptance.

### R8 — Freeze once development is ready, then assess fresh families

1. Require R1–R7 completion evidence, development usefulness checks and repeated
   latency headroom before spending effort on another test set. Retain all prior
   failed assessments; repeated new tests are not a substitute for fixing the loop.
2. Freeze the implementation revision, owner-approved acceptance-v10 numeric gates
   (including the 2,000 ms maximum warm p95; every other numeric gate remains
   unchanged), selected profile, scoring/report versions and timing procedure. Purely
   operational optimization should preserve ranking configuration; record code changes
   even if the profile ID remains unchanged.
3. Prepare fresh source-reviewed held-out families under the established protocol.
   Keep test questions, judgments and origins inaccessible to tuning; document source,
   modality/category coverage, review effort and assistant-review limitations.
4. Run the declared baselines and selected configuration once under the frozen
   procedure. Report all attempts, uncertainty, effective modes, resources and limits.
   A failed gate remains failed; subsequent repairs return to development.
5. Mark Phase 2 accepted only when every frozen gate and implementation obligation
   passes. Then update the source of truth, roadmap, handoff, README, operations and
   decision records coherently, with Phase 3 inputs and known limitations.

**Done:** reproducible, honest Phase 2 acceptance. No new corpus, answer generation,
public deployment or larger infrastructure is needed for this plan.
