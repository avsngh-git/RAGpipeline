# 2. Getting started

There are three ways to run the platform, in increasing order of effort:

| Path | Needs | Gives you |
| --- | --- | --- |
| [CPU demo](#cpu-demo) | Docker, about 12 GB disk, 8 GB RAM | Search over the 100-paper corpus, eight stored research runs, the web page, the API and MCP |
| [Live research runs](#live-research-runs-gpu) | The above, plus an NVIDIA GPU with the NVIDIA Container Toolkit | New research runs with the local model |
| [Development environment](#development-environment) | Conda, Docker | Running the tests, changing the code, building corpora |

## CPU demo

```bash
git clone https://github.com/avsngh-git/RAGpipeline.git
cd RAGpipeline
scripts/demo_load.sh
docker compose up -d
```

`scripts/demo_load.sh` is idempotent. It:

1. checks for `docker`, `docker compose`, `curl`, `sha256sum` and `tar`;
2. downloads `research-demo-v1.tar` from the [`demo-data-v1` release](https://github.com/avsngh-git/RAGpipeline/releases/tag/demo-data-v1) into `demo-data/`, verifies its SHA-256 and unpacks it;
3. pulls the API image (`ghcr.io/avsngh-git/ragpipeline:latest`), or builds it locally if the pull fails;
4. starts PostgreSQL and Qdrant and runs `research-migrate`;
5. loads the bundle's PostgreSQL rows and Qdrant snapshots with `research-demo load` (once, guarded by `demo-data/.loaded-v1`);
6. fetches the pinned embedding and reranker models into the `model_cache` volume with `research-demo fetch-models`;
7. creates a `read`-scoped API key for principal `demo` and saves it to `demo-data/api-key` (mode 600);
8. starts the API, waits for `/ready`, and prints the web page URL and one link per showcase run.

After it finishes:

- **Web page.** Open `http://127.0.0.1:8000/`, paste the contents of `demo-data/api-key`, and search, or open a showcase run link (`http://127.0.0.1:8000/#run=<run_id>`).
- **API.** `curl -H "Authorization: Bearer $(cat demo-data/api-key)" http://127.0.0.1:8000/v1/serving`. See the [HTTP API](04-http-api.md).
- **MCP.** Point a client at `http://127.0.0.1:8000/mcp/` with the same bearer key. See [MCP](05-mcp.md).
- **Smoke check.** `python3 scripts/demo_smoke.py` runs the checks CI runs: readiness, serving identity, paper and evidence search, the stored runs and the MCP tool list.

### Options

| Variable or flag | Effect |
| --- | --- |
| `COMPOSE_PROJECT_NAME`, `POSTGRES_PORT`, `QDRANT_PORT`, `API_PORT` | Run beside another checkout without sharing containers, volumes or ports. Compose otherwise names the project after the directory. |
| `RESEARCH_PLATFORM_IMAGE` | Use a specific image tag or digest instead of `latest`, for example `ghcr.io/avsngh-git/ragpipeline:v0.6.0`. |
| `--reset` | Runs `docker compose down -v`, deleting **all** Compose volumes (PostgreSQL, Qdrant, model cache), then loads the demo again. |
| `--with-llm` | Also starts Ollama and gives the demo key `research` scope. See below. |

### Disk and memory

The parts add up to about 7.5 GB: the API image (4.2 GB), the PostgreSQL and Qdrant images (0.7 GB), the bundle and its unpacked copy (0.7 GB), the loaded data (about 0.8 GB) and the two models (about 1.2 GB). The demo ran on an 11 GB laptop VM and on a standard GitHub runner.

### If something fails

- **Model download fails.** The models are pinned to exact Hugging Face revisions. If a revision has been removed upstream, `fetch-models` fails loudly rather than loading a different model.
- **`/ready` returns 503.** The response names the dependency that is down. See [Operations: failure recovery](13-operations.md#failure-recovery).
- **The load refuses because collections exist.** You are probably sharing a Compose project with another checkout; set `COMPOSE_PROJECT_NAME`.

## Live research runs (GPU)

Generating answers needs the local model, Qwen3.5-2B `Q4_K_M`, on Ollama with all layers on an NVIDIA GPU. It needs about 1.8 GB of GPU memory at the default 32K context.

```bash
scripts/demo_load.sh --with-llm
scripts/phase3_fetch_generator.sh 2b          # downloads and checks the pinned GGUF
docker compose --profile llm exec -T ollama ollama create qwen3.5-2b-text:q4_k_m \
  -f /dev/stdin < configs/ollama/qwen3.5-2b-text.Modelfile
```

Then start a run:

```bash
KEY=$(cat demo-data/api-key)
curl -s -X POST http://127.0.0.1:8000/v1/research \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"question": "Does reranking improve retrieval-augmented generation?", "mode": "quick"}'
```

Poll `GET /v1/research/{run_id}` until the status is `completed` or `failed`. With thinking enabled, a run takes about 2 to 7 minutes on an RTX 3050. In the Compose demo, retrieval still runs on CPU inside the API container, which is slower. For the fastest path, the owner's setup runs the API in the host Conda environment with retrieval on the GPU beside Ollama; see the [generator guide](../operations/phase-3-generator.md).

Check the model is fully on the GPU:

```bash
docker compose --profile llm exec ollama ollama ps   # PROCESSOR must be "100% GPU"
```

## Development environment

The project uses Conda for its environment and an editable install of the package from `src/`.

```bash
conda env create --file environment.yaml
conda activate sci_research_agent
python -m pip install --no-deps --require-hashes -r requirements-bm25s.txt
python -m pip install --no-deps --require-hashes -r requirements-langgraph.txt
python -m pip install --no-build-isolation --no-deps -e .
```

To reproduce CI exactly, build from the lock instead: `conda create --name sci_research_agent --file environment-linux-64.lock`, then the same three `pip` lines. The lock contains no PyTorch; tests that need models are skipped or use fakes.

Run the checks:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
```

Keep the checkout outside the system temporary directory: a Phase 3 evaluation script refuses to run from there to protect private data, and its test fails at import.

### Local services

`docker compose up -d postgres qdrant` starts the databases on loopback ports 5432 and 6333. Apply migrations with `research-migrate` (or `python scripts/migrate.py`).

Integration tests need **disposable** services and skip otherwise:

```bash
export RESEARCH_PLATFORM_TEST_DATABASE_URL=postgresql://research:research@localhost:5432/research_test
export RESEARCH_PLATFORM_TEST_QDRANT_URL=http://localhost:6333
python -m pytest tests/integration
```

The database must be named `research_test`. The tests apply migrations to it and create and delete temporary Qdrant collections.

### Running the API from source

```bash
export RESEARCH_PLATFORM_AUTH_MODE=disabled      # loopback only; every request runs as "local"
python -m uvicorn research_platform.api.app:create_app --factory --host 127.0.0.1 --port 8001
```

Without a loaded snapshot the API is live (`/health`) but not ready (`/ready` reports which runtime failed to start). To serve search from source, either load the demo bundle into your local services with `research-demo load`, or build a corpus as described in [Corpus and ingestion](08-corpus-and-ingestion.md). Search also needs the optional model dependencies (`pip install -e '.[embeddings]'`) or the serving lock described in the [serving environment guide](../operations/serving-environment.md).

Next: [How it works](03-how-it-works.md).
