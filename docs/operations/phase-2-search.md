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
  -p 127.0.0.1:36333:6333 qdrant/qdrant:v1.14.1

export RESEARCH_PLATFORM_TEST_DATABASE_URL='postgresql://research_test:research_test@127.0.0.1:35432/research_test'
export RESEARCH_PLATFORM_TEST_QDRANT_URL='http://127.0.0.1:36333'
conda run -n sci_research_agent python -m pytest -m integration

docker stop ragpipeline-phase2-test-postgres

docker stop ragpipeline-phase2-test-qdrant
```

Never point integration tests at `research_phase1_review`, `research`, or the serving
Qdrant service. The tests create schemas and temporary collections in their dedicated
targets.

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

## Prepare optional local models

The base Conda environment pins NumPy 2.5.3 for BM25S; the exact Linux lock
contains NumPy and its BLAS libraries. Ordinary CI omits model weights and the optional
inference runtime. The `embeddings` extra pins `sentence-transformers==6.1.0` and
`transformers==5.17.0`. In an operator environment, install PyTorch for the host first,
then install the project extra and verify its dependencies. In WSL, verify CUDA
from the same Conda environment used to run the API:

```bash
conda run -n sci_research_agent python -m pip install '.[embeddings]'
conda run -n sci_research_agent python -m pip check
conda run -n sci_research_agent python -c 'import torch; print(torch.cuda.is_available())'
```

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

Create local BM25 and hybrid lexical artifacts from the accepted review database:

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
profile and the artifact/cache paths explicitly:

```bash
export RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE=trusted_private_local
export RESEARCH_PLATFORM_LEXICAL_INDEX_ROOT="$PWD/local-reference/phase2-indexes"
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

- Missing or invalid lexical artifacts fail runtime readiness. Rebuild them with the
  exact profile manifest and review database.
- Missing Qdrant points, stale filter metadata, or a mismatched profile fail closed.
  Rebuild the named Phase 2 collection and wait for its exact reconciliation report.
- Do not use the accepted Phase 1 E5 collection as a repair target.
- `permission_denied` means the API server was not configured for private-local
  evidence access. Changing a request does not grant that access.
- A 503 or `/ready` response with `phase2_search: unavailable` requires checking the
  database selection, Qdrant, lexical artifacts, and pinned model caches.
- Keep raw evaluation outputs mode 0600 under `local-reference/`. Clean only named
  disposable test containers, temporary model caches, or obsolete derived Phase 2
  artifacts after confirming they are not the configured serving paths.
