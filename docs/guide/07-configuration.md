# 7. Configuration

All runtime configuration comes from environment variables, and it is validated when the process starts. An invalid value raises a clear `ValueError` at startup instead of failing later. The main settings live in [`config.py`](../../src/research_platform/config.py); authentication, tracing and the worker read a few more.

`.env.example` lists safe local values. The application does not load `.env` itself. Docker Compose reads it for interpolation; on the host, export the variables in your shell. `.env` is git-ignored; keep real credentials there.

## Core

| Variable | Default | Values and meaning |
| --- | --- | --- |
| `RESEARCH_PLATFORM_ENVIRONMENT` | `development` | `development`, `test` or `production`. Production refuses unsafe options (disabled auth, `full` traces, `trusted_private_client`). |
| `RESEARCH_PLATFORM_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `RESEARCH_PLATFORM_DATABASE_URL` | `postgresql://research:research@localhost:5432/research` | PostgreSQL URL |
| `RESEARCH_PLATFORM_QDRANT_URL` | `http://localhost:6333` | Qdrant URL |
| `RESEARCH_PLATFORM_DEPENDENCY_TIMEOUT_SECONDS` | `2` | Timeout for each readiness check |
| `RESEARCH_PLATFORM_MIGRATIONS_DIR` | the repository's `migrations/` | The image sets `/app/migrations` |

## Search and models

| Variable | Default | Meaning |
| --- | --- | --- |
| `RESEARCH_PLATFORM_MODEL_DEVICE` | `auto` | `auto`, `cpu` or `cuda` for the embedding and reranker models. Compose uses `cpu`. |
| `RESEARCH_PLATFORM_RERANKER_CACHE_DIR` | none | Directory holding the pinned reranker files |
| `HF_HOME`, `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` | Hugging Face defaults | Compose sets `/models/hf` and offline mode after `fetch-models` |
| `RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE` | `disabled` | `trusted_private_local` enables evidence text in search responses. A request cannot grant it. |
| `RESEARCH_PLATFORM_GENERATION_COLLECTION` | `research-corpus` | Which collection's published generation to serve |
| `RESEARCH_PLATFORM_GENERATION_CONFIGURATION` | `configs/phase35-generation-index-lexical.example.json` | Generation index configuration (Qdrant collection names and lexical settings) |
| `RESEARCH_PLATFORM_CONTENT_SOURCE` | `qdrant` | Where evidence text is read: `qdrant` or `postgres` |
| `RESEARCH_PLATFORM_LEXICAL_ENGINE` | `qdrant` | `qdrant` (sparse vectors) or `bm25s` (in-process fallback and parity oracle) |
| `RESEARCH_PLATFORM_PHASE2_PROFILE` | the active profile pointer | Override the frozen retrieval profile file, for example for the `bm25s` fallback |
| `RESEARCH_PLATFORM_LEXICAL_INDEX_ROOT` | `local-reference/phase2-indexes` | BM25S index files; only for `bm25s` |

The served retrieval profile is chosen by [`benchmarks/phase2/active-profile.toml`](../../benchmarks/phase2/active-profile.toml), which points at a frozen profile and checks its digest. Changing a model or ranking setting means a new profile and a new evaluation, not an environment variable.

## Generator

| Variable | Default | Meaning |
| --- | --- | --- |
| `RESEARCH_PLATFORM_LLM_BASE_URL` | `http://localhost:11434` | Ollama URL. Compose uses `http://ollama:11434`. |
| `RESEARCH_PLATFORM_LLM_MODEL` | `qwen3.5-2b-text:q4_k_m` | Ollama model name |
| `RESEARCH_PLATFORM_LLM_TIMEOUT_SECONDS` | `1200` | Per-call timeout, up to 3,600 |
| `RESEARCH_PLATFORM_LLM_CONTEXT_TOKENS` | `32768` | Sent as `num_ctx` with every call; 2,048 to 262,144. Keep Ollama's `OLLAMA_CONTEXT_LENGTH` equal. |
| `RESEARCH_PLATFORM_LLM_THINKING` | `plan,evaluate,synthesize` | Which call kinds use thinking |
| `RESEARCH_PLATFORM_LLM_SEED` | `20261001` | Base sampling seed; synthesis retries use the next seeds |

Sampling (temperature 1.0, top_k 20, top_p 0.95, presence penalty 1.5) is sent explicitly with every call and recorded, so the request, not the Ollama model file, decides it.

## Online discovery

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPENALEX_API_KEY` | none | Needed for discovery, citation enrichment and OpenAlex content downloads. It is never written into configurations or URLs. |

Discovery budgets are code defaults in `DiscoverySettings`, not environment variables: 10 OpenAlex searches and 5 downloads per run, 5 papers per ingestion wait, a $0.50 daily spend cap across all runs, English, and 2020 onward.

## Authentication and limits

| Variable | Default | Meaning |
| --- | --- | --- |
| `RESEARCH_PLATFORM_AUTH_MODE` | `api_key` (`disabled` in `test`) | `disabled` is refused in production or on a non-loopback bind host |
| `RESEARCH_PLATFORM_API_BIND_HOST` | `127.0.0.1` | Declares the bind host for the loopback check |
| `RESEARCH_PLATFORM_RATE_LIMIT_<CLASS>` | see [HTTP API: limits](04-http-api.md#limits) | `capacity/seconds` per principal; classes `RESEARCH_CREATE`, `SEARCH`, `PAPER_READ`, `RUN_READ`, `INGEST` |
| `RESEARCH_PLATFORM_MAX_ACTIVE_RUNS_PER_KEY` | `2` | Queued, running or waiting runs per principal |
| `RESEARCH_PLATFORM_MAX_BODY_BYTES` | `65536` | Request body limit |
| `RESEARCH_PLATFORM_API_KEY` | none | Key used by the `agent-dev` evaluation suite when it calls the API |

## MCP

| Variable | Default | Meaning |
| --- | --- | --- |
| `RESEARCH_PLATFORM_MCP_TEXT_POLICY` | `public_display_only` | Or `trusted_private_client`; see [MCP](05-mcp.md#passage-text) |
| `RESEARCH_PLATFORM_MCP_ALLOWED_HOSTS` | `127.0.0.1:*,localhost:*,[::1]:*` | Comma-separated `Host` patterns |
| `RESEARCH_PLATFORM_MCP_ALLOWED_ORIGINS` | empty | Comma-separated allowed `Origin` values |

## Observability

| Variable | Default | Meaning |
| --- | --- | --- |
| `RESEARCH_PLATFORM_TRACING` | on, except in `test` | `on` or `off` |
| `RESEARCH_PLATFORM_TRACE_CONTENT` | `full` in development, `ids` elsewhere | `none`, `ids` or `full`; `full` is refused in production |
| `RESEARCH_PLATFORM_TRACE_DIR` | `local-reference/traces` in development, none elsewhere | JSONL trace directory; empty disables JSONL |
| `RESEARCH_PLATFORM_OTLP_ENDPOINT` | none | OTLP HTTP endpoint, for example a self-hosted Langfuse |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | none | Credentials sent to the OTLP endpoint |

## Worker

See [`research-worker`](06-cli.md#research-worker).

## Compose-only variables

`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`, `QDRANT_PORT`, `API_PORT`, `OLLAMA_PORT`, `RESEARCH_PLATFORM_IMAGE`, `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_KV_CACHE_TYPE` and `LLAMA_ARG_CACHE_RAM` configure the containers in [`docker-compose.yml`](../../docker-compose.yml). All published ports bind to `127.0.0.1` ([ADR-0006](../adr/0006-compose-loopback-host-bindings.md)). `LLAMA_ARG_CACHE_RAM` (default 1,024 MiB) caps llama.cpp's host-memory prompt cache. Without it, the cache once grew to 6.8 GiB and was killed for running out of memory; see the [generator guide](../operations/phase-3-generator.md#host-memory-llama-server-prompt-cache).

## Configuration files

| Path | Contents |
| --- | --- |
| `configs/` | Versioned JSON for discovery, chunking, indexing and generations; Ollama model files |
| `benchmarks/phase2/` | Frozen retrieval profiles, the active-profile pointer and acceptance configurations |
| `benchmarks/phase3/` | Scripted regression cases |
| `environment.yaml` | The human-maintained Conda environment |
| `environment-linux-64.lock` | Exact test and development environment (no PyTorch), used by CI |
| `environment-serving-linux-64.lock` | Exact CPU serving environment, used to build the image |
| `requirements-*.txt` | Hash-pinned wheels installed on top of the locks |

Next: [Corpus and ingestion](08-corpus-and-ingestion.md).
