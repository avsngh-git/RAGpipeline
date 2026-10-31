# Scientific Research Platform

A self-hosted research assistant for scientific literature. You ask a research question; it searches its indexed collection of papers (and can look up newer work on OpenAlex), gathers evidence passages and tables, and writes an answer in which **every claim carries a quote copied from its source, which code checks against the cited passage**. Each answer is stored with enough provenance (snapshot, index generation, models, prompts, configuration hash, trace) to explain how it was produced and to rebuild its configuration later.

It runs entirely on local infrastructure: FastAPI, PostgreSQL, Qdrant, a LangGraph agent and a small local language model (Qwen3.5-2B on Ollama). It was developed on a laptop with a 4 GB RTX 3050. No hosted LLM API is involved.

> **Status:** v1.0.0 is released and Phase 6 is complete: the CPU demo passes its smoke checks on a fresh GitHub runner ([Phase 6 gate report](docs/reference/phase-6-gate-report.md)). Answer quality is the main open problem; see [Limitations](#limitations).

## Video

A live deep research run on the project's reference question, recorded on a laptop with an RTX 3050 GPU. The agent's 4 min 43 s of work is shown accelerated; the question and the answer play at normal speed.

https://github.com/user-attachments/assets/6bf3debb-862c-4f89-822d-042e13705d83

## The problem it addresses

Retrieval-augmented generation (RAG) systems often cite sources that do not say what the answer claims. This project treats the citation as the product. It accepts a claim only if:

1. the claim cites a passage that retrieval actually returned during this run;
2. the claim's quote appears in that passage: exactly for table rows, and with at most small differences such as hyphenation for prose; and
3. the claim says nothing its quote does not. At least half of its content words, every number, and words like "both", "significantly" or "highest" must come from the quote.

A claim that fails any of these checks is dropped, and the drop is recorded. The model does not grade its own citations; deterministic code does.

## How it works

```mermaid
flowchart LR
    Q["Question"] --> API["FastAPI<br/>/v1/research"]
    API --> AGENT["LangGraph agent<br/>quick or deep_research"]
    AGENT -->|typed tools| SEARCH["Hybrid search<br/>sparse BM25 + dense gte<br/>RRF fusion, Ettin reranker"]
    SEARCH --> QD[("Qdrant<br/>derived index")]
    AGENT -->|cited evidence| LLM["Local LLM<br/>Qwen3.5-2B on Ollama"]
    LLM -->|draft claims + quotes| VERIFY["Quote verification<br/>in code"]
    VERIFY --> PG[("PostgreSQL<br/>authoritative records")]
    MCP["MCP clients<br/>/mcp"] --> CAP["Shared research<br/>capabilities"]
    API --> CAP
    CAP --> SEARCH
```

1. **Corpus.** Papers are discovered through OpenAlex and downloaded only when a license record permits it. Docling extracts their sections and tables, which are chunked by section into source-linked evidence units. The accepted corpus is 100 CC BY papers and 44,277 searchable chunks, frozen as a *finalized snapshot*.
2. **Index.** Each finalized snapshot is published to Qdrant as a numbered *index generation*, which holds dense vectors, sparse lexical vectors and the evidence text. PostgreSQL stays authoritative, so the index can be verified against it and rebuilt from it.
3. **Search.** A query runs lexical (BM25 over Qdrant sparse vectors) and dense (`gte-modernbert-base`) retrieval. Reciprocal Rank Fusion combines them, and the `Ettin-150M` cross-encoder reranks the top 16. Results keep every component rank and score.
4. **Research run.** `POST /v1/research` queues a run. In `quick` mode the agent follows a fixed search → evidence → answer path. In `deep_research` mode the model plans batches of typed tool calls (search, citations, related papers, OpenAlex discovery, ingestion requests) and decides when evidence suffices. Code enforces budgets on rounds, tool calls, time and retries.
5. **Answer.** The model sees evidence through short run-local handles (`E1`–`E40`) and must quote the passage it cites. Code verifies each claim, then assigns an outcome: `answered`, `partially_supported` or `insufficient_evidence`.
6. **Record.** PostgreSQL stores the effective configuration, every tool call, model call and drafted claim with its verdict. `research-runs explain` names the stage where a run lost its answer, and `research-runs reproduce` re-derives its configuration hash.

The same capabilities serve HTTP routes, the agent's tools and an MCP server. CI checks that the three surfaces return the same results and that the MCP adapter cannot import storage or ranking code directly.

The [documentation guide](docs/guide/README.md) explains each step in depth.

## Try it (about 10 minutes, CPU only)

The commands are implemented by [`scripts/demo_load.sh`](scripts/demo_load.sh). On 2026-10-14 a fresh clone completed it in 634 seconds on a laptop CPU, most of it downloading the image, the bundle and the models.

```bash
TAG=v1.0.0  # the release tag you check out; see https://github.com/avsngh-git/RAGpipeline/releases
git clone --branch "$TAG" https://github.com/avsngh-git/RAGpipeline.git
cd RAGpipeline
export RESEARCH_PLATFORM_IMAGE="ghcr.io/avsngh-git/ragpipeline:$TAG"
scripts/demo_load.sh
```

Set `RESEARCH_PLATFORM_IMAGE` to the release tag you checked out before running the script; without it Compose uses `:latest`, which may be an older image already on the machine. The script leaves the stack running; `docker compose up -d` restarts it later.

The loader downloads the [`demo-data-v2`](https://github.com/avsngh-git/RAGpipeline/releases/tag/demo-data-v2) bundle (the 100-paper corpus, its search indexes and eight showcase runs, including their model-call text), verifies its checksum and prepares the local services ([Phase 6 plan](docs/plans/phase-6-portfolio.md), [display policy](docs/adr/0032-phase6-public-cc-by-demo-collection.md)). Then open `http://127.0.0.1:8000/`, paste the key saved in `demo-data/api-key`, and open one of the showcase run links printed by the script. The page lets you search the released collection and inspect its showcase runs. Public display is limited to material cleared by the document review ([ADR-0031](docs/adr/0031-phase5-external-passage-exposure.md), [ADR-0032](docs/adr/0032-phase6-public-cc-by-demo-collection.md)).

The UI supports paper and evidence search with filters and paper pages.
Browse the eight showcase runs, their records and their recorded model-call text.
Starting a live run needs a GPU and the optional `llm` profile; CPU small mode supports search and run inspection. See the [UI guide](docs/operations/ui.md) for pages, scopes and model-text behavior.

Requirements: Docker with Compose v2 ([Compose configuration](docker-compose.yml)), about 11.1 GB free disk, and 8 GB RAM. Measured on 2026-10-29, the parts add up to 9.2 GB: the API image (4.2 GB), the PostgreSQL and Qdrant images (0.8 GB), the bundle and its unpacked copy (0.8 GB), the loaded data (2.4 GB: Qdrant 1.8 GB, PostgreSQL 0.6 GB) and the two models (1.0 GB); the free-disk figure adds 20%. It ran on a laptop VM with 11 GB of memory and on a standard GitHub runner.

If you already run another checkout of this project with Docker Compose, give the demo its own project name and ports so the two stacks do not share containers or volumes; Compose names a project after its directory:

```bash
export COMPOSE_PROJECT_NAME=ragdemo POSTGRES_PORT=55432 QDRANT_PORT=56333 API_PORT=18000
scripts/demo_load.sh
```

The script then prints links on the chosen `API_PORT`.

### Check the demo

`python3 scripts/demo_smoke.py` (standard library only) runs the eleven checks against `http://127.0.0.1:${API_PORT:-8000}`; it reads `API_PORT`, or pass `--base-url`.

### Remove the demo

Run `docker compose down -v` with the same `COMPOSE_PROJECT_NAME`, then delete the clone. Docker creates `data/` inside the clone as root, so deleting it needs `sudo`.

Call the API directly with the same key ([HTTP API guide](docs/guide/04-http-api.md)), or connect an MCP client to `http://127.0.0.1:8000/mcp/` (or your `API_PORT`) ([MCP guide](docs/guide/05-mcp.md)).

## Results

All numbers come from one 100-paper corpus with assistant-reviewed relevance labels. They support directional conclusions, not claims about scientific literature in general.

| What was measured | Result | Caveat |
| --- | --- | --- |
| Retrieval, one-time held-out assessment (30 question families) | 16 of 16 frozen gates passed; evidence nDCG@10 0.407, paper nDCG@10 0.652, warm p95 1.0 s on the RTX 3050 | Three quality gates passed by margins inside sampling noise, and their thresholds were lowered for that one fresh set after v13 failed ([ADR-0015](docs/adr/0015-phase2-acceptance-gate-revision.md)). Dense-only search ranked *papers* better (0.718). |
| Reranking, paired on the same set | Evidence nDCG@10 +0.043 (95% CI +0.010 to +0.075); direct-evidence MRR@10 +0.204 | No effect on paper ranking. |
| Agent runs (21 development tasks × 2 modes) | 42 of 42 completed within budget, with no unknown evidence handles | Operational gate only. |
| Answers on the same tasks | Latest 42-run sweep: 5 answered, 25 partially supported, 12 insufficient evidence | Answer quality was reported, never gated. |
| Run reproduction (Phase 4) | 5 of 5 accepted walkthroughs reproduced | `reproduce` matches at each run's recorded commit, not with current code ([backlog #115](https://github.com/avsngh-git/RAGpipeline/issues/115), [Phase 4 gate report](docs/reference/phase-4-gate-report.md)). |
| Quote verification, reviewed sample | Rejected 7 of 15 partial or unsupported claims and 2 of 60 supported ones | It filters bad claims but also drops some good ones. |

Details, intervals and baselines (BM25-only, dense-only, hybrid without reranking, fixed-window chunking) are in [Benchmarks](docs/reference/benchmarks.md). Failed assessments and rejected experiments are in [Failure analysis](docs/reference/failure-analysis.md).

## Design decisions

Each choice has an Architecture Decision Record (ADR) in [`docs/adr/`](docs/adr/).

| Decision | Why | ADR |
| --- | --- | --- |
| PostgreSQL is authoritative; Qdrant is a derived, rebuildable index | Provenance and permissions must survive an index loss or rebuild | [0022](docs/adr/0022-phase35-qdrant-search-and-content.md), [0023](docs/adr/0023-phase35-index-generations.md) |
| Numbered index generations; each run pins one | Adding papers must not silently change a running or past run's corpus | [0023](docs/adr/0023-phase35-index-generations.md) |
| Hybrid search with a reranker, chosen by held-out evaluation | Measured against lexical-only, dense-only and unreranked hybrid | [0017](docs/adr/0017-phase2-accepted-profile-v10.md) |
| One bounded LangGraph agent, not a multi-agent cast | Fewer moving parts; budgets and stop conditions enforced in code | [0019](docs/adr/0019-phase3-research-run-execution.md) |
| A 2B local model with thinking enabled, no output cap | Fits beside retrieval on a 4 GB GPU; the owner chose precision over latency | [0021](docs/adr/0021-phase3-qwen35-2b-gpu.md), [0025](docs/adr/0025-verified-quote-synthesis-with-thinking.md) |
| Claims verified by quote matching in code, not by an LLM judge | Deterministic, explainable and testable | [0025](docs/adr/0025-verified-quote-synthesis-with-thinking.md), [0029](docs/adr/0029-claim-scope-words-and-prompt-trials.md) |
| Hashed API keys with scopes, per-key rate limits, run ownership | Enough security for a self-hosted service | [0027](docs/adr/0027-phase4-authentication-and-rate-limits.md) |
| OpenTelemetry traces with content levels, plus PostgreSQL run records | Traces explain timing; run records decide what happened | [0026](docs/adr/0026-phase4-observability-and-run-records.md) |
| One MCP server inside the API process, over the same services | No duplicated logic; models load once on the small GPU | [0030](docs/adr/0030-phase5-mcp-adapter.md), [0031](docs/adr/0031-phase5-external-passage-exposure.md) |
| Released image plus a local CPU demo instead of hosting | No recurring cost | [0033](docs/adr/0033-phase6-delivery-without-hosting.md) |

The project deliberately leaves out generator fine-tuning, Kubernetes, a graph database, Spark and multi-agent personas. The [architecture overview](docs/architecture/overview.md) explains why.

## Limitations

- **Small corpus.** 100 papers on retrieval and RAG. Results do not generalize beyond it.
- **Answer quality.** The 2B model often declares evidence insufficient when reviewed evidence partly answers the question (57 of 131 synthesis calls in one review). Two prompt trials did not fix this.
- **Planner.** In `deep_research` mode the 2B planner rarely chooses evidence search, OpenAlex discovery or ingestion on its own. Code therefore starts every first plan with whole-question searches and, when an OpenAlex key is configured, discovery ([backlog #115](https://github.com/avsngh-git/RAGpipeline/issues/115)).
- **Automatic ingestion.** Ingestion stops at papers whose tables are flagged for manual review, which blocks many table-heavy papers.
- **Labels.** Relevance labels and judgments are assistant-reviewed, not independently human-verified.
- **CPU mode.** The demo runs retrieval on CPU. Its latency is not benchmarked, and new research runs need a GPU.

## Documentation

| Start here | For |
| --- | --- |
| [Documentation guide](docs/guide/README.md) | Concepts, setup, how it works, API, MCP, CLI, configuration, operations, development |
| [Architecture overview](docs/architecture/overview.md) | Components, request sequence, security model |
| [Benchmarks](docs/reference/benchmarks.md) and [failure analysis](docs/reference/failure-analysis.md) | Measured results and known failures |
| [Deployment and operations](docs/operations/deployment.md) | Releases, migrations, backup, rollback, recovery |
| [Project specification](docs/agents/scientific-research-platform-source-of-truth.md) | Requirements, locked decisions, delivery phases |
| [Project history](docs/history.md) | Phase-by-phase record |
| [Glossary](CONTEXT.md) | Domain vocabulary |

## Development

The [development guide](docs/guide/14-development.md) covers the code layout, test suites, CI and conventions.

Create the Conda environment and install the package in editable mode ([environment definition](environment.yaml)):

`conda env create --file environment.yaml` creates an environment named `sci_research_agent`; add `--name <yours>` if that name is taken (and activate that name instead).

```bash
conda env create --file environment.yaml
conda activate sci_research_agent
python -m pip install --no-deps --require-hashes -r requirements-bm25s.txt
python -m pip install --no-deps --require-hashes -r requirements-langgraph.txt
python -m pip install --no-build-isolation --no-deps -e .
python -m playwright install --with-deps chromium
```

The last line installs the Chromium that the browser tests use, as CI does. On WSL or without root, install the system libraries and the browser separately: `sudo "$(which python)" -m playwright install-deps chromium`, then `python -m playwright install chromium`.

CI builds the same environment from the exact lock instead (`conda create --name sci_research_agent --file environment-linux-64.lock`, then the three `pip` lines; see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)). Keep the checkout outside the system temporary directory: the Phase 3 evaluation script refuses to run from there to protect private data, and its test fails at import.

Run the project checks from the repository root:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
```

Integration tests skip unless `RESEARCH_PLATFORM_TEST_DATABASE_URL` and `RESEARCH_PLATFORM_TEST_QDRANT_URL` point to disposable services. The PostgreSQL URL must use a dedicated `research_test` database; tests apply migrations and enforce constraints. CI supplies fresh service containers ([evaluation operations](docs/operations/evaluation.md)). See also the [observability](docs/operations/observability.md), [retention](docs/operations/retention.md), [authentication](docs/operations/authentication.md), and [serving environment](docs/operations/serving-environment.md) guides.

### Integration test services

Start the same disposable services CI uses ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)), then point the tests at them. Change the host ports if 5432 or 6333 are taken, and never point these variables at a database you want to keep:

```bash
docker run -d --rm --name research-test-postgres -p 127.0.0.1:5432:5432 \
  -e POSTGRES_DB=research_test -e POSTGRES_USER=research -e POSTGRES_PASSWORD=research \
  postgres:16-alpine
docker run -d --rm --name research-test-qdrant -p 127.0.0.1:6333:6333 \
  qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10
export RESEARCH_PLATFORM_TEST_DATABASE_URL=postgresql://research:research@127.0.0.1:5432/research_test
export RESEARCH_PLATFORM_TEST_QDRANT_URL=http://127.0.0.1:6333
python -m pytest
docker stop research-test-postgres research-test-qdrant
```

## Data and licences

The code is licensed under [MIT](LICENSE). The demo passages are excerpts from CC BY papers and are listed in the bundle's `ATTRIBUTION.md`. Only documents that passed a per-document display review are included ([ADR-0032](docs/adr/0032-phase6-public-cc-by-demo-collection.md)). Send takedown requests through a [GitHub issue](https://github.com/avsngh-git/RAGpipeline/issues/new).
