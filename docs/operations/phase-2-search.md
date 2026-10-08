# Phase 2 search operations

**Status:** assistant-reviewed 2026-09-28. R8 v12 completed with 8/14 gates passing;
the selected profile passed warm p95 at 894.3 ms against the 2,000 ms gate, while six
quality/source gates failed. Phase 2 remains open and the v12 set is sealed from
tuning. Use development data for repairs, then prepare a new source-reviewed held-out
set. See the [completion plan](../plans/phase-2-improvement-plan.md),
[handoff](../plans/phase-2-agent-handoff.md), and
[current acceptance report](../reference/phase-2-acceptance-report.md).

## Service boundary

Phase 2 search is a trusted private-local service. The API must bind to loopback and
must set `RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE=trusted_private_local` on the
server. A request cannot grant this permission. Do not expose the service through a
public tunnel or paste search results, evidence IDs, passages, model caches, or private
run files into public logs or issue reports.

The accepted snapshot is in the local `research_phase1_review` PostgreSQL database.
The default Compose database named `research` does not contain it. The serving profile
uses the separately named `phase2-e5-small-v2-filtered` Qdrant collection and the
profile/configuration recorded in `benchmarks/phase2/`. The retained
`phase1-e5-small-v2` collection is not a Phase 2 rebuild target.

The active profile is selected through
[`active-profile.toml`](../../benchmarks/phase2/active-profile.toml), which verifies
the frozen manifest digest and profile ID. Runtime startup, the ingestion CLI,
packaging, and profile tests use this pointer. Historical manifests remain available
for replay. The active profile binds to the exact 44,277 selected evidence units,
retains the filter-ready Phase 2 collection and reranks the first 16 fused candidates.
On success it appends the remaining candidates in hybrid order; an over-budget pair
or typed inference failure returns the complete unchanged hybrid pool. The model,
512-token pair budget, corpus and acceptance thresholds remain unchanged. The accepted
Phase 1 collection remains separate.

## API error responses

Every handled error uses one envelope: `{"error": {"code", "message", "request_id"}}`.

Since 2026-10-08, errors raised by FastAPI or Starlette themselves use it too, with the
exception's own detail text not exposed:
- `404 not_found`
- `405 method_not_allowed`, keeping the `Allow` header
- `413 request_too_large`
- `400 invalid_request`

Before this, 404 and 405 returned FastAPI's bare `{"detail": …}`.

The 64 KiB body limit returns 413 both when `Content-Length` is too large and when a
body sent without that header (in chunks) goes over the limit while being read. FastAPI
0.141.1 turns any exception raised while parsing a model-bound body into
`400 "There was an error parsing the body"` unless it is an `HTTPException`. So the limit
raises a 413 `HTTPException`; until 2026-10-08 such bodies got that 400.

## Small checks

Create the regular project environment and install the package using the steps in the
[README](../../README.md#development-environment). The small profile does not download
model weights or require a GPU:

```bash
conda run -n sci_research_agent python -m ruff check .
conda run -n sci_research_agent python -m ruff format --check .
conda run -n sci_research_agent python -m mypy
conda run -n sci_research_agent python -m pytest -m 'not integration'
```

For disposable service integration checks, use a dedicated database named
`research_test` and a separate Qdrant service. These example containers have no
persistent volumes:

```bash
docker run -d --rm --name ragpipeline-phase2-test-postgres \
  -e POSTGRES_DB=research_test \
  -e POSTGRES_USER=research_test \
  -e POSTGRES_PASSWORD=research_test \
  -p 127.0.0.1:35432:5432 postgres:16-alpine

docker run -d --rm --name ragpipeline-phase2-test-qdrant \
  -p 127.0.0.1:36333:6333 qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10

export RESEARCH_PLATFORM_TEST_DATABASE_URL='postgresql://research_test:research_test@127.0.0.1:35432/research_test'
export RESEARCH_PLATFORM_TEST_QDRANT_URL='http://127.0.0.1:36333'
conda run -n sci_research_agent python -m pytest -m integration

docker stop ragpipeline-phase2-test-postgres

docker stop ragpipeline-phase2-test-qdrant
```

Never point integration tests at `research_phase1_review`, `research`, or the serving
Qdrant service. The tests create schemas and temporary collections in their dedicated
targets.

## Qdrant version

Compose and CI pin Qdrant v1.19.1 (Phase 3.5, P35-03). Qdrant only guarantees storage
compatibility across one minor version, so the 2026-10-04 move from v1.14.1 used export
and import instead of an in-place upgrade:

```bash
python scripts/phase35_qdrant_migrate.py export --url http://127.0.0.1:6333 \
  --directory local-reference/phase35/qdrant-export
docker compose up -d qdrant   # new image and new volume qdrant_data_v1_19
python scripts/phase35_qdrant_migrate.py import --url http://127.0.0.1:6333 \
  --directory local-reference/phase35/qdrant-export
```

Import checks each collection's exact count, a payload digest, every vector within
1e-6, and exact-search probes. All four local collections passed. The previous volume
`ragpipeline_qdrant_data` (v1.14.1 storage) is kept unmodified for rollback: point the
Compose service back at it together with the old image. The export holds private
evidence text and stays under `local-reference/`.

## Index generations (Phase 3.5)

Generations put a collection's finalized snapshots into Qdrant collections that serve
both search and evidence content ([ADR-0022](../adr/0022-phase35-qdrant-search-and-content.md),
[ADR-0023](../adr/0023-phase35-index-generations.md)). With the database and Qdrant URLs
exported as below:

```bash
CONFIG=configs/phase35-generation-index-lexical.example.json   # the serving configuration
research-ingest generations build --collection-name research-corpus \
  --snapshot-id <finalized snapshot> --configuration $CONFIG \
  [--reuse-dense-generation-configuration <configuration with the same dense model>]
research-ingest generations sync-papers --collection-name research-corpus \
  --configuration $CONFIG --generation <N>
research-ingest generations verify --collection-name research-corpus \
  --configuration $CONFIG --generation <N>
research-ingest generations publish --collection-name research-corpus \
  --configuration $CONFIG --generation <N>
research-ingest generations purge --collection-name research-corpus \
  --configuration $CONFIG            # add --apply to delete
research-ingest generations rebuild --collection-name research-corpus \
  --configuration $CONFIG            # into empty collections, from PostgreSQL
```

`verify` compares exact evidence IDs, text hashes, payload fields, indexed papers and
self-retrieval probes with the snapshot. `publish` only moves the pointer from the
previous generation. Research runs record the generation they read. Generation dense
search is exact rather than approximate.

**Serving defaults since the Phase 3.5 cutover (P35-17, 2026-10-05).** The active profile is
`frozen-profile-v10-qdrant.toml`, and the defaults are `RESEARCH_PLATFORM_CONTENT_SOURCE=qdrant`,
`RESEARCH_PLATFORM_LEXICAL_ENGINE=qdrant` and
`RESEARCH_PLATFORM_GENERATION_CONFIGURATION=configs/phase35-generation-index-lexical.example.json`.
Qdrant serves evidence content, dense search and `scientific_bm25` lexical search from the
published generation of that configuration (`research-passages-gte-bm25-v1`,
`research-papers-gte-bm25-v1`). Lexical index files are no longer needed for serving. v10-qdrant
inherits the Phase 2 acceptance through the
[lexical parity report](../reference/phase-3.5-lexical-parity-report.md).

The in-process BM25S path remains the fallback and the parity oracle. To serve it, set
`RESEARCH_PLATFORM_LEXICAL_ENGINE=bm25s`,
`RESEARCH_PLATFORM_PHASE2_PROFILE=benchmarks/phase2/frozen-profile-v10.toml` and
`RESEARCH_PLATFORM_LEXICAL_INDEX_ROOT`, and build the lexical artifacts as described below.
Qdrant still serves content and dense search in that mode.

The runtime serves any published generation of the configured collection. When the frozen
profile's own snapshot is not published in that collection (for example the leave-out
corpus, `RESEARCH_PLATFORM_GENERATION_COLLECTION=leave-out-dev` with its configuration in
`local-reference/phase35/leaveout-dev-generation-index.json`), the API serves the
collection's published generation. New research runs pin the generation published when
they start.

`purge --apply` deletes only points no published generation or unfinished run can read.
Never delete a Qdrant collection shared by several snapshots (for example
`phase1-e5-small-v2`): remove one snapshot's points with a `snapshot_id` filter instead.

## Online discovery and ingestion (Phase 3.5)

[ADR-0024](../adr/0024-phase35-online-discovery-and-ingestion.md): in `deep_research` runs
the agent may call `discover_papers` (OpenAlex search, abstracts as labelled evidence) and
`request_ingestion`; `POST /v1/collections/{collection_id}/ingest` uses the same path.
Code decides every proposed paper (`online-membership-v1`) and records it in
`ingestion_decisions`; accepted papers become one `ingestion_requests` row.

- **Budgets** (`DiscoverySettings`): 10 OpenAlex searches and 5 downloads per run, 5 papers
  per wait, a daily spend cap of $0.50 shared by all runs, English and 2020 onward. A
  `deep_research` run waits at most `max_ingestion_wait_seconds` (900) for its request,
  outside its active-time budget, then switches once to the newly published generation.
- **OpenAlex key:** discovery and OpenAlex content downloads need `OPENALEX_API_KEY`.
- **Merged OpenAlex works (changed 2026-10-08):** OpenAlex answers a merged work's old ID
  with a 301 redirect to the new one. The client turns it into `OpenAlexMoved` (old ID, new
  ID), where it previously failed with "unexpected redirect".
  - **Citation enrichment** follows the redirect once and stores the new work's metadata
    under the cited ID, with `merged_from` set to that ID.
  - **Curated lookups** (corpus membership metadata and configured older-paper exceptions)
    stop with a message naming the new ID, since the curated list needs updating.
- **Cost from headers (changed 2026-10-08):** when a response has no `meta.cost_usd`, the
  cost comes from `X-RateLimit-Credits-Used`, which counts credits of $0.0001 each. It was
  previously read as dollars. Searches report `meta.cost_usd`, so the spend ledger was
  unaffected.
- **Worker:** a separate process in the host Conda environment, one request at a time:

  ```bash
  RESEARCH_PLATFORM_INGESTION_HANDLER=online \
  RESEARCH_PLATFORM_ARTIFACT_ROOT=data/artifacts \
  research-worker            # SIGINT or SIGTERM stops it cleanly
  ```

  It claims requests with leases (a crashed worker's request is reclaimed), holds the
  PostgreSQL GPU advisory lock, unloads the Ollama model, acquires each permitted PDF
  (exact-file permission, reusing a stored copy), extracts with Docling, chunks with the
  published snapshot's chunking configuration, then finalizes a child snapshot
  (`policy:online-ingestion-v1`) and builds, verifies and publishes the next generation.
  Papers without a permitted route stay metadata-only; a paper whose extraction needs a
  manual flagged-table review is refused (`validation:flagged_table_review_pending`).
- **Figure text (changed 2026-10-08, owner decision):** text inside a picture (axis ticks,
  legend entries, panel labels, figure OCR) is kept as evidence and labelled with the
  heading `Figure text` under its section. It does not change the document's heading
  path, even when Docling labels a large figure label as a section header. Captions keep
  their `Figure caption` heading.
  - **Before,** this text became unlabelled body sections.
  - **Why it is kept:** Phase 2 judges cited it as evidence: 1,520 of the 6,070 text
    sections in the source alignments are figure fragments, such as chart values.
  - **Identifying new extractions:** their configuration carries
    `picture_children: labelled-figure-text`, so they have new configuration and
    extraction IDs.
  - **The existing corpus is unchanged.** Its 14,622 figure fragments (33% of indexed
    chunks, averaging 14 characters) stay indexed without the label, so the Phase 2
    judgments and scores remain valid. Grouping fragments per figure would be a later,
    measured change.
- **Docling** is the repository's pinned `pdf` extra. Install it without changing the CUDA
  PyTorch build: install `torchvision` from the PyTorch index matching the installed
  `torch`, then the `pdf` pins with a constraints file that holds `torch`, `numpy` and
  `transformers`. RapidOCR downloads its OCR models on first use.
- **Average-length drift:** when a new generation's evidence average length drifts more
  than 10% from the configuration, the generation details record
  `new_configuration_recommended`; a new configuration is not created automatically.

## Start local dependencies

Start PostgreSQL and Qdrant from Compose without its API container:

```bash
docker compose up -d postgres qdrant
```

The Compose ports bind to `127.0.0.1`. Set the database URL explicitly before every
Phase 2 command so work cannot fall back to the empty `research` database:

```bash
export RESEARCH_PLATFORM_DATABASE_URL='postgresql://research:research@localhost:5432/research_phase1_review'
export RESEARCH_PLATFORM_QDRANT_URL='http://localhost:6333'
```

The review database must already contain the finalized snapshot, the exact selected
chunk relation, permission evidence, and the applied migrations. The API does not run
migrations. The `research-ingest index rebuild` command currently runs the migration
runner before rebuilding; use it only with the explicit review database above or a
separate disposable database.

## Copy the gte index into the main stack

Historical. The `phase2-dev-gte-modernbert-base-v1` collection was deleted at the Phase 3.5
cutover on 2026-10-05; its vectors and payloads are exported under
`local-reference/phase35/qdrant-export/`. Serving now reads generation collections.

The accepted profile v10 used the `phase2-dev-gte-modernbert-base-v1` collection. The
index was built in the isolated `p2_eval_20260927` stack for the one-time assessment;
copy it into the main stack before serving profile v10. The evaluation PostgreSQL
database is named `research_test` and remains disposable. Do not point the main API at
it. The copy script checks that both databases select the same exact snapshot chunks,
that the source index is ready, and that the target collection is absent. It transfers
a Qdrant collection snapshot through ignored `local-reference/` storage, removes the
temporary source snapshot, copies the index registration in one database transaction,
and verifies the target point count and serving readiness.

Start the existing evaluation services and the main database/vector services:

```bash
docker compose -p p2_eval_20260927 start postgres qdrant
docker compose -p p2_eval_20260927 ps
docker compose up -d postgres qdrant
```

The evaluation services bind to `127.0.0.1:25432` (PostgreSQL) and
`127.0.0.1:26333` (Qdrant). Main services bind to `127.0.0.1:5432` and
`127.0.0.1:6333`. Supply the database passwords already configured for each local
container through shell environment variables; do not commit them or paste them into
logs. URL-encode any reserved characters in a password before putting it in a URL. Set
the URLs explicitly so the copy cannot target the disposable test database:

```bash
export SOURCE_DATABASE_URL="postgresql://research_test:${P2_EVAL_POSTGRES_PASSWORD}@127.0.0.1:25432/research_test"
export SOURCE_QDRANT_URL="http://127.0.0.1:26333"
export TARGET_DATABASE_URL="postgresql://research:${POSTGRES_PASSWORD:-research}@127.0.0.1:5432/research_phase1_review"
export TARGET_QDRANT_URL="http://127.0.0.1:6333"
```

Preview and then perform the copy:

```bash
conda run -n sci_research_agent python scripts/phase2_copy_dense_index.py \
  --source-database-url "$SOURCE_DATABASE_URL" \
  --source-qdrant-url "$SOURCE_QDRANT_URL" \
  --target-database-url "$TARGET_DATABASE_URL" \
  --target-qdrant-url "$TARGET_QDRANT_URL" \
  --collection phase2-dev-gte-modernbert-base-v1 \
  --snapshot-id 4b11fab3-d4a5-4e7a-a58e-8654accf2c6c --dry-run

conda run -n sci_research_agent python scripts/phase2_copy_dense_index.py \
  --source-database-url "$SOURCE_DATABASE_URL" \
  --source-qdrant-url "$SOURCE_QDRANT_URL" \
  --target-database-url "$TARGET_DATABASE_URL" \
  --target-qdrant-url "$TARGET_QDRANT_URL" \
  --collection phase2-dev-gte-modernbert-base-v1 \
  --snapshot-id 4b11fab3-d4a5-4e7a-a58e-8654accf2c6c
```

If the target collection already exists, the script stops without overwriting it. Do
not delete or rebuild a target collection as an automatic retry; inspect its registration
and point count first. The source evaluation collection is read-only apart from the
temporary snapshot that the script deletes after transfer.

The Qdrant restore and PostgreSQL transaction cannot commit atomically. If the
registration fails after restore, the target collection remains and a retry refuses
to overwrite it. Before recovery, confirm the source still passes readiness and has
44,277 points, then inspect the target's `index_configurations` and
`snapshot_index_states` for this collection and configuration. Remove only a target
collection confirmed to be an orphan from this failed copy, with no registered
snapshot using it; then repeat the dry-run and copy. If registration committed but
final verification failed, keep the target collection and registration, diagnose the
count or readiness mismatch, and verify both search routes before serving it.

Start the host API in the main-stack configuration using the environment in
[Run the real-model API on WSL](#run-the-real-model-api-on-wsl), with the main review
database URL and Qdrant URL above. Use a free loopback port if another API already owns
8000. Send one synthetic request to each search route; inspect only the status, result
status, hit count, and whether reranker scores are present. Do not print or save hit
content, titles, paper IDs, or evidence IDs. Both routes should return HTTP 200,
`ranked_candidates`, `reranked`, and at least one reranker score. The frozen profile v10
ID is `sha256:52a152db9fb350c91810353650864eaffef0b3fe148fde9781956373d3fe5449`.

## Model precision (changed 2026-10-08)

- **Embedders load in the precision they declare.** transformers 5 loads the dtype in a
  model's `config.json` when none is passed.
  - **For gte-modernbert** that file says `float16`, so the default `fp32` embedder
    actually ran in fp16 for queries, for generation builds and in the ingestion worker.
  - **The fix:** the embedder now passes `dtype` explicitly, float32 for `fp32`. An `fp16`
    embedder loads in float16 directly instead of calling `.half()` after loading. `fp16`
    still requires CUDA.
- **Measured effect, on the 21 agent development questions, with the same index:**
  - fp16 and fp32 query embeddings agree to a cosine of at least 0.9996.
  - Dense top-10 results are identical for all 21 questions, in the same order for 19.
  - Top-50 results share 49.95 of 50 on average.
  - `retrieval-dev` on the v13 development set scored the same before and after
    (experiments `4e96dba5…` and `a64c8f14…`). Only 2 of its questions had scorable
    judgments.
- **The index was not rebuilt.** Stored passage vectors are equally close to fp16 and
  fp32 encodings (cosine 0.999998), so neither precision can be shown to have built it,
  and the difference is negligible.
- **A half-precision reranker refuses CPU.** The active Ettin profile reranks in fp16.
  When no GPU is available, the reranker now raises `RerankerDeviceUnavailable`, and
  search returns the unchanged hybrid order, as for other typed reranker failures.
  Before, it reranked in fp16 on CPU, a numeric path the profile was never measured on.

## Prepare optional local models

The base Conda environment pins NumPy 2.5.3 for BM25S; the exact Linux lock
contains NumPy and its BLAS libraries. Ordinary CI omits model weights and the optional
inference runtime.

The `embeddings` extra pins `torch==2.14.0`, `sentence-transformers==6.1.0` and
`transformers==5.17.0`. The PyTorch pin was added on 2026-10-08; until then PyTorch was
pinned nowhere.

In an operator environment, install the pinned PyTorch build for the host first, then
install the project extra and verify its dependencies. The CUDA 13.0 build used here
comes from the PyTorch index, and `==2.14.0` also matches its `+cu130` label. In WSL,
verify CUDA from the same Conda environment used to run the API:

```bash
conda run -n sci_research_agent python -m pip install 'torch==2.14.0' \
  --index-url https://download.pytorch.org/whl/cu130
conda run -n sci_research_agent python -m pip install '.[embeddings]'
conda run -n sci_research_agent python -m pip check
conda run -n sci_research_agent python -c 'import torch; print(torch.cuda.is_available())'
```

Each research run records the installed build as `torch_version` in its effective
configuration, for example `2.14.0+cu130`. PyTorch does not guarantee identical results
across releases or platforms.
- **How it is read:** from `torch/version.py`, without importing torch, so the API and
  `research-runs reproduce` record the same value. The package metadata drops the CUDA
  label.
- **Effect on `reproduce`:** runs from before 2026-10-08 lack the field, so it reports
  `torch_version` as a difference for them.

On 2026-10-08 a stale `torch-2.12.0+cpu.dist-info` folder left by an earlier install was
moved out of the `sci_research_agent` environment, to `local-reference/env-backup/`.
- **Why it was moved, not uninstalled:** `pip uninstall` would have deleted files the
  installed 2.14.0 build shares with it.
- **Checked afterwards:** `pip check` reported no broken requirements, and torch imported
  with CUDA available.

The profiles pin E5-small-v2 at revision
`e8b23a92af33fd81c865283d505f8f058a570cc8` and MiniLM at revision
`233902d25c440f23af6f7d6e94d2946bac0bee0a`. Before the first offline start, place
those exact revisions in local Hugging Face caches. For example, with model downloads
enabled only for this explicit preparation step:

```bash
export HF_HOME="$PWD/local-reference/phase2-model-cache"
export RESEARCH_PLATFORM_RERANKER_CACHE_DIR="$PWD/local-reference/phase2-reranker-cache"
python -c 'from huggingface_hub import snapshot_download; snapshot_download("intfloat/e5-small-v2", revision="e8b23a92af33fd81c865283d505f8f058a570cc8"); snapshot_download("cross-encoder/ms-marco-MiniLM-L6-v2", revision="233902d25c440f23af6f7d6e94d2946bac0bee0a", cache_dir="local-reference/phase2-reranker-cache")'
```

The first call stores E5 under `HF_HOME`; the second stores the reranker in its
explicit cache directory. Choose stable local paths with enough space; `/tmp` is
appropriate only for disposable diagnostics because it may be cleared between WSL
sessions. Both paths are ignored by Git and excluded from Docker build context. After
preparation, set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` before startup. The
runtime resolves the active profile pointer and loads only the pinned local revisions.
Readiness fails if either cache is absent or incomplete; startup does not download
weights in offline mode. Verify `/ready`, then exercise both `POST /v1/search` and
`POST /v1/evidence/search` with the private local client and check status/counts only;
do not log response text or identifiers.

## Build and verify indexes

Lexical artifacts are needed only for the BM25S fallback and the parity scripts. Create
local BM25 and hybrid lexical artifacts from the accepted review database:

```bash
umask 077
research-ingest index lexical-build \
  --profile benchmarks/phase2/bm25-profile-v1.toml \
  --output-root local-reference/phase2-indexes
research-ingest index lexical-build \
  --profile benchmarks/phase2/hybrid-e5-profile-v1.toml \
  --output-root local-reference/phase2-indexes
```

Build or repair only the isolated filter-ready Phase 2 dense collection with the
tracked configuration:

```bash
research-ingest index rebuild \
  --snapshot-id 4b11fab3-d4a5-4e7a-a58e-8654accf2c6c \
  --configuration benchmarks/phase2/e5-small-v2-filtered-index-v1.json \
  --device auto
```

Use `--device cpu` when CUDA is unavailable. `--device cuda` fails if CUDA is not
visible to WSL. Rebuild publication occurs only after exact selected-ID and filter
payload reconciliation succeeds. A failed rebuild is not ready to serve.

Check the exact collection and point count without printing evidence IDs:

```bash
research-ingest index inspect \
  --snapshot-id 4b11fab3-d4a5-4e7a-a58e-8654accf2c6c \
  --configuration benchmarks/phase2/e5-small-v2-filtered-index-v1.json
research-ingest snapshots validate \
  --snapshot-id 4b11fab3-d4a5-4e7a-a58e-8654accf2c6c \
  --minimum-papers 100
```

Lexical artifacts, model caches, private run records, and downloaded sources stay
under ignored local paths. Do not clean or rebuild `phase1-e5-small-v2` as part of
Phase 2 operations.

## Run the real-model API on WSL

Run Uvicorn in the host Conda environment so it can use WSL CUDA and the local model
caches. Compose supplies only PostgreSQL and Qdrant. Export the server-side access
profile and the cache paths explicitly:

```bash
export RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE=trusted_private_local
export RESEARCH_PLATFORM_MODEL_DEVICE=auto
export RESEARCH_PLATFORM_RERANKER_CACHE_DIR="$PWD/local-reference/phase2-reranker-cache"
export HF_HOME="$PWD/local-reference/phase2-model-cache"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

conda run -n sci_research_agent python -m uvicorn \
  research_platform.api.app:create_app --factory \
  --host 127.0.0.1 --port 8000
```

Use `RESEARCH_PLATFORM_MODEL_DEVICE=cpu` for CPU-only service. The app warms both
models and checks profile/index bindings during startup. `/health` reports process
liveness. `/ready` reports dependency and Phase 2 runtime readiness. Search endpoints
return a stable 503 when a required index, database, Qdrant service, or model is
unavailable; profile mismatches fail closed. Search requests have a 30-second total
deadline. A timed-out reranker call can leave one active inference finishing on the
single model worker; new reranker work fails fast and uses only the frozen explicit
hybrid fallback.

Available routes are `POST /v1/search`, `POST /v1/evidence/search`,
`GET /v1/papers/{paper_id}`, `GET /v1/papers/{paper_id}/references`, and
`GET /v1/papers/{paper_id}/citations`. Search scores are ranking signals. Responses do
not assert answerability or claim support.

## Development evaluation and source review

The tracked development decisions and sanitized metrics are in
[the Phase 2 report](../research/phase-2-development-report.md). Full local result
records and the replay scripts are access-restricted under
`local-reference/phase2-runs/p2-14-validation/`; they are intentionally excluded from
Git with the raw query/passage/candidate provenance. On the original WSL workspace,
replay and score the development matrix with:

```bash
umask 077
PYTHONPATH=src:/tmp/ragpipeline-phase2/bm25s-pilot/pydeps \
  conda run -n sci_research_agent \
  python local-reference/phase2-runs/p2-14-validation/run-retrieval-matrix.py
PYTHONPATH=src:/tmp/ragpipeline-phase2/bm25s-pilot/pydeps \
  conda run -n sci_research_agent \
  python local-reference/phase2-runs/p2-14-validation/score-retrieval-matrix.py
```

The runner uses the disposable Qdrant service at `127.0.0.1:26333` and offline
model caches. Its private inputs and outputs are not part of a clean checkout; the
sanitized report is the portable result.

For bounded warm-latency and typed fallback diagnostics on the synthetic fixture and
allowlisted development families only, use the tracked
[`phase2_dev_benchmark.py`](../../scripts/phase2_dev_benchmark.py) command. It requires
an explicit allowlist, records stage timings and safe response fingerprints, and
writes mode-0600 output to `/tmp` by default. Reproduce comparisons with three
sessions of 100 warm requests, six warm-ups, fixed device/thread/concurrency/load
settings and the same input/profile. Do not supply q20/q21, any spent assessment, or
files whose name ends in `origins.json`.

The v2 profile prefix-cap ablation can be reproduced on the original workspace after
the v1 local development inputs are present:

```bash
umask 077
PYTHONPATH=src:/tmp/ragpipeline-phase2/bm25s-pilot/pydeps \
  conda run -n sci_research_agent \
  python local-reference/phase2-runs/p2-14-validation/run-poolcap-dev-v1.py
PYTHONPATH=src:/tmp/ragpipeline-phase2/bm25s-pilot/pydeps \
  conda run -n sci_research_agent \
  python local-reference/phase2-runs/p2-14-validation/score-poolcap-dev-v1.py
```

These scripts use only q01–q10 and q11–q19. Raw outputs remain mode 0600 in
local-reference and do not include held-out families. For source-only table rechecks in the original
workspace, the bounded audit scripts are:

```bash
python local-reference/phase2-runs/p2-14-validation/inspect-table-anchor-coordinates.py
python local-reference/phase2-runs/p2-14-validation/inspect-table-rowgroup-ranges.py
python local-reference/phase2-runs/p2-14-validation/inspect-source-only-table-coordinates.py
```

Those scripts depend on ignored local review inputs and the original workspace path.
Their sanitized conclusions are in
[the q12/q14 table audit](../research/phase-2-q12-q14-table-candidate-audit.md).
Source judgments and table checks follow the
[Phase 2 evaluation protocol](../plans/phase-2-evaluation-protocol.md). Keep held-out
query text, cards, labels, and all `*origins.json` files sealed until the local
implementation/CI gate and freeze checks pass.

## Rebuild, failure, and cleanup

- With the Qdrant lexical engine (the default), startup fails unless content comes from
  Qdrant, the generation configuration has lexical settings, the profile names the Qdrant
  lexical identity and the snapshot has a published generation.
- With `RESEARCH_PLATFORM_LEXICAL_ENGINE=bm25s`, missing or invalid lexical artifacts fail
  runtime readiness. Rebuild them with the exact profile manifest and review database.
- Missing Qdrant points, stale filter metadata, or a mismatched profile fail closed.
  Rebuild the named Phase 2 collection and wait for its exact reconciliation report.
- Do not use the accepted Phase 1 E5 collection as a repair target.
- `permission_denied` means the API server was not configured for private-local
  evidence access. Changing a request does not grant that access.
- A 503 or `/ready` response with `phase2_search: unavailable` requires checking the
  database selection, Qdrant, the published generation (or lexical artifacts under BM25S),
  and pinned model caches.
- Keep raw evaluation outputs mode 0600 under `local-reference/`. Clean only named
  disposable test containers, temporary model caches, or obsolete derived Phase 2
  artifacts after confirming they are not the configured serving paths.
