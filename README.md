# Scientific Research Platform

A self-hosted research assistant for scientific literature. You ask a research question; it searches a fixed collection of papers, gathers evidence passages and tables, and writes an answer in which **every claim carries a quote copied from its source, which code checks against the cited passage**. Each answer is stored with enough provenance (snapshot, index generation, models, prompts, configuration hash, trace) to explain how it was produced and to rebuild its configuration later.

It runs entirely on local infrastructure: FastAPI, PostgreSQL, Qdrant, a LangGraph agent and a small local language model (Qwen3.5-2B on Ollama). It was developed on a laptop with a 4 GB RTX 3050. No hosted LLM API is involved.

> **Status:** v0.6.0 is released, and the CPU demo passes its smoke checks on a fresh GitHub runner ([Phase 6 gate report](docs/reference/phase-6-gate-report.md)). Answer quality is the main open problem; see [Limitations](#limitations).

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

Requirements: Docker with Compose v2, `curl`, `sha256sum`, about 12 GB free disk and 8 GB RAM. No GPU is needed.

```bash
git clone https://github.com/avsngh-git/RAGpipeline.git
cd RAGpipeline
scripts/demo_load.sh
docker compose up -d
```

[`scripts/demo_load.sh`](scripts/demo_load.sh) downloads the [`demo-data-v1`](https://github.com/avsngh-git/RAGpipeline/releases/tag/demo-data-v1) bundle (354 MB: the 100-paper corpus, its search index and eight showcase research runs) and verifies its checksum. It then pulls the released image, applies migrations, loads the data, fetches the pinned embedding and reranker models, and creates a read-only API key in `demo-data/api-key`. On a laptop CPU a fresh clone took 568–634 seconds, mostly downloads.

Then:

- open `http://127.0.0.1:8000/`, paste the key, and search the collection or open a showcase run (the script prints run links);
- call the API directly. See the [HTTP API guide](docs/guide/04-http-api.md);
- connect an MCP client to `http://127.0.0.1:8000/mcp/` with the same key. See the [MCP guide](docs/guide/05-mcp.md).

If another checkout of this project already runs under Docker Compose, give the demo its own project name and ports:

```bash
export COMPOSE_PROJECT_NAME=ragdemo POSTGRES_PORT=55432 QDRANT_PORT=56333 API_PORT=18000
scripts/demo_load.sh && docker compose up -d
```

The CPU demo searches the corpus and shows stored research runs. Starting **new** research runs needs the local LLM on an NVIDIA GPU (`scripts/demo_load.sh --with-llm`); see [Getting started](docs/guide/02-getting-started.md#live-research-runs-gpu).

<!-- TODO(owner): add the recorded demo video link here (P6-18). -->

## Results

All numbers come from one 100-paper corpus with assistant-reviewed relevance labels. They support directional conclusions, not claims about scientific literature in general.

| What was measured | Result | Caveat |
| --- | --- | --- |
| Retrieval, one-time held-out assessment (30 question families) | 16 of 16 frozen gates passed; evidence nDCG@10 0.407, paper nDCG@10 0.652, warm p95 1.0 s on the RTX 3050 | Three quality gates passed by margins inside sampling noise, and their thresholds were lowered after an earlier set failed. Dense-only search ranked *papers* better (0.718). |
| Reranking, paired on the same set | Evidence nDCG@10 +0.043 (95% CI +0.010 to +0.075); direct-evidence MRR@10 +0.204 | No effect on paper ranking. |
| Agent runs (21 development tasks × 2 modes) | 42 of 42 completed within budget, with no unknown evidence handles | Operational gate only. |
| Answers on the same tasks | Latest 42-run sweep: 5 answered, 25 partially supported, 12 insufficient evidence | Answer quality was reported, never gated. |
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
- **Planner.** In `deep_research` mode the planner almost never chooses OpenAlex discovery or ingestion on its own; it keeps to local search ([backlog #115](https://github.com/avsngh-git/RAGpipeline/issues/115)).
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

```bash
conda env create --file environment.yaml
conda activate sci_research_agent
python -m pip install --no-deps --require-hashes -r requirements-bm25s.txt
python -m pip install --no-deps --require-hashes -r requirements-langgraph.txt
python -m pip install --no-build-isolation --no-deps -e .

python -m ruff check . && python -m ruff format --check . && python -m mypy && python -m pytest
```

Integration tests run only when `RESEARCH_PLATFORM_TEST_DATABASE_URL` and `RESEARCH_PLATFORM_TEST_QDRANT_URL` point to disposable services. The [development guide](docs/guide/14-development.md) covers the code layout, test suites, CI and conventions.

## Data and licences

The code is licensed under [MIT](LICENSE). The demo passages are excerpts from CC BY papers and are listed in the bundle's `ATTRIBUTION.md`. Only documents that passed a per-document display review are included ([ADR-0032](docs/adr/0032-phase6-public-cc-by-demo-collection.md)). Send takedown requests through a [GitHub issue](https://github.com/avsngh-git/RAGpipeline/issues/new).
