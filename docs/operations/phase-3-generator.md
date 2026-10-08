# Phase 3 local generator

This guide prepares the Phase 3 generator: the text-only Qwen3.5-2B `Q4_K_M` GGUF
([ADR-0021](../adr/0021-phase3-qwen35-2b-gpu.md)), imported into Ollama with every layer
on the GPU. Ollama runs in the optional Compose `llm` profile. The API runs in the host
Conda environment, keeps the Phase 2 retrieval models (gte + Ettin) on the same GPU, and
reaches Ollama at `http://127.0.0.1:11434`.

## Prerequisites

- Docker Desktop or Docker Engine with the NVIDIA Container Toolkit configured
  for the Docker daemon. Verify GPU access with `docker run --rm --gpus all
  nvidia/cuda:12.9.0-base-ubuntu22.04 nvidia-smi`.
- An NVIDIA GPU and driver compatible with the installed container runtime.
- WSL memory set to 12 GB (`%UserProfile%\\.wslconfig` on Windows).
- About 1.5 GB free for the model file, plus Docker image and Ollama model storage.

The Compose service pins `ollama/ollama:0.35.0` to multi-platform index digest
`sha256:2a6e883b917fc543389599dae79918f5cac9e1438890506982f44aa4f5625d01`.
The Linux AMD64 manifest is
`sha256:9c1dc45ea758396139ec0adfa52947714c61f8d1e4537a6e2daef8138e7a64a9`.
The index and manifest were checked on 2026-10-01 against the
[Ollama Docker Hub tag](https://hub.docker.com/layers/ollama/ollama/0.35.0/images/sha256-9c1dc45ea758396139ec0adfa52947714c61f8d1e4537a6e2daef8138e7a64a9).

## Fetch and import

`scripts/phase3_fetch_generator.sh` downloads the pinned text-only GGUF into the ignored
`local-reference/phase3-models/` directory and checks its SHA-256. It never downloads a
vision projector (`mmproj-*`) file.

| Argument | File | Hugging Face revision | SHA-256 |
| --- | --- | --- | --- |
| `2b` (default, active) | `unsloth/Qwen3.5-2B-GGUF` `Qwen3.5-2B-Q4_K_M.gguf` (1,280,835,840 bytes) | `f6d5376be1edb4d416d56da11e5397a961aca8ae` | `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223` |
| `4b` (comparison only) | `unsloth/Qwen3.5-4B-GGUF` `Qwen3.5-4B-Q4_K_M.gguf` | `35edb278feb3f797d270a605d9745cab09538c12` | `00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4` |

```bash
scripts/phase3_fetch_generator.sh 2b
docker compose --profile llm up -d ollama
docker compose --profile llm exec -T ollama ollama create qwen3.5-2b-text:q4_k_m \
  -f /dev/stdin < configs/ollama/qwen3.5-2b-text.Modelfile
```

`configs/ollama/qwen3.5-2b-text.Modelfile` uses the `qwen3.5` renderer and parser and
sets `PARAMETER num_gpu 99`. Ollama's automatic layer fit otherwise leaves layers on the
CPU even when GPU memory is free, which cut the 4B model to about 1 token/second.
`configs/ollama/qwen3.5-4b-text.Modelfile` imports the 4B the same way for comparisons.

Without the `llm` profile, `docker compose up` starts only PostgreSQL, Qdrant and the API.
Imported models are kept in the `ollama_models` named volume.

## Smoke checks

```bash
docker compose --profile llm exec ollama ollama show qwen3.5-2b-text:q4_k_m
```

The capabilities must include `completion`, `tools` and `thinking`, and must not include
`vision`. After a request loads the model, check its placement:

```bash
docker compose --profile llm exec ollama ollama ps
```

The `PROCESSOR` column must say `100% GPU`. With `num_gpu 99` an out-of-memory load fails
instead of silently splitting layers onto the CPU.

Check thinking output and schema-constrained JSON with thinking off:

```bash
curl --fail-with-body http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5-2b-text:q4_k_m","messages":[{"role":"user","content":"Think briefly, then answer: what is 2 + 2?"}],"think":true,"stream":false}'

curl --fail-with-body http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5-2b-text:q4_k_m","messages":[{"role":"user","content":"Return an answer to the question: what is 2 + 2?"}],"think":false,"stream":false,"format":{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}}'
```

The first reply must have a non-empty `message.thinking`; the second must have
`message.content` that parses as JSON with an `answer` string.

## GPU sharing with retrieval

Measured on 2026-10-03 on the RTX 3050 Laptop GPU (4,096 MiB; Ollama sees about
3.2 GiB free) with Ollama 0.35.0 and a 16,384-token context:

| Loaded on the GPU | GPU memory |
| --- | ---: |
| Retrieval models (gte + Ettin), idle | 713 MiB |
| Retrieval while reranking 16 long pairs | 1,361 MiB |
| Retrieval idle + Qwen3.5-2B text `Q4_K_M` | 2,286 MiB |
| Peak while reranking and generating at the same time | 2,934 MiB |

Generation ran at 81.7 tokens/second alone and 63.5 tokens/second while reranking;
reranking 16 pairs took 1.2 s either way. On CPU the same rerank took 183–216 s, so
research runs keep retrieval on the GPU (`RESEARCH_PLATFORM_MODEL_DEVICE=auto` or `cuda`).
The 4B text-only model needs 3,343 MiB by itself and does not fit beside retrieval.

## Fitness check

The P3-04 fitness set contains 15 synthetic prompts and invented results; it does not
read private Phase 2 questions or corpus passages. Run it from the repository root in the
`sci_research_agent` environment with the review database, Qdrant, and the model imported:

```bash
export RESEARCH_PLATFORM_DATABASE_URL='postgresql://research:research@localhost:5432/research_phase1_review'
export RESEARCH_PLATFORM_RERANKER_CACHE_DIR="$PWD/local-reference/phase2-reranker-cache"
export RESEARCH_PLATFORM_LEXICAL_INDEX_ROOT="$PWD/local-reference/phase2-indexes"
export HF_HOME="$PWD/local-reference/phase2-model-cache" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RESEARCH_PLATFORM_LLM_MODEL=qwen3.5-2b-text:q4_k_m \
python scripts/phase3_generator_fitness.py \
  --arrangement gpu-shared --repetitions 3 \
  --think-repetitions 1 --think-repair-attempts 0 \
  --output local-reference/phase3-runs/fitness/qwen3.5-2b-text-v3-gpu-shared.json
```

`gpu-shared` loads the Phase 2 runtime on CUDA before calling Ollama; `retrieval-cpu`
loads it on CPU. The script checks for `100% GPU` placement, samples GPU memory every
0.5 seconds, and measures schema-constrained JSON for every call kind and native tool calls
for the six plan cases, each with thinking off and on. Plan prompts list the six tools
with the same descriptions as the P3-10 prompt. Thinking calls get 2,048 output tokens on
top of each call's cap (384 plan, 192 evaluate and judge, 768 synthesize), because
Ollama counts thinking tokens against `num_predict`. Thinking-on calls can take minutes,
so the shortened protocol above runs them once with no repair attempts.

The output records model identity, placement, peak memory, the protocol settings and
per-call validity, score, latency and token counts. It omits prompt and response text.
`complete: false` marks a partial run. Keep outputs under ignored `local-reference/phase3-runs/`
and record only aggregates in ADR-0021.

## Running research

The API and Phase 2 retrieval models run in the host `sci_research_agent` environment.
Point the service at the reviewed serving database and the local frozen artifacts before
starting it:

```bash
export RESEARCH_PLATFORM_DATABASE_URL='postgresql://research:research@localhost:5432/research_phase1_review'
export RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE=trusted_private_local
export RESEARCH_PLATFORM_LEXICAL_INDEX_ROOT="$PWD/local-reference/phase2-indexes"
export RESEARCH_PLATFORM_RERANKER_CACHE_DIR="$PWD/local-reference/phase2-reranker-cache"
export RESEARCH_PLATFORM_MODEL_DEVICE=auto
export HF_HOME="$PWD/local-reference/phase2-model-cache"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

conda run -n sci_research_agent python -m uvicorn \
  research_platform.api.app:create_app --factory \
  --host 127.0.0.1 --port 8001
```

Submit a research request and use its returned `run_id` to inspect progress. Requests and
answers are private local research data; keep saved request/view/tool-call records under
the ignored `local-reference/phase3-runs/` directory. The API response includes claims and
evidence handles with paper metadata, not passage text.

```bash
curl --fail-with-body http://127.0.0.1:8001/v1/research \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which retrieval methods improve evidence ranking?","mode":"quick"}'

curl --fail-with-body http://127.0.0.1:8001/v1/research \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which retrieval methods improve evidence ranking?","mode":"deep_research"}'

curl --fail-with-body http://127.0.0.1:8001/v1/research/RUN_ID
research-runs show RUN_ID
```

Synthesis thinks with no output cap ([ADR-0025](../adr/0025-verified-quote-synthesis-with-thinking.md)):
expect about 2 to 7 minutes per run on the RTX 3050. The defaults are
`RESEARCH_PLATFORM_LLM_THINKING=plan,evaluate,synthesize` (evaluate added on 2026-10-07, Phase 4 owner decision 7; evaluation is then uncapped like synthesis), a 32,768-token context, a 1,200-second
call timeout and a 1,800-second run budget. A view's claims each carry the `quote` that
code verified against the cited passage; apply migration 017 (`scripts/migrate.py`) to the
serving database before running this version.

One worker executes one run at a time. Runs left queued or running by a process restart
are resumed at startup from their PostgreSQL records and LangGraph checkpoints. A changed
effective configuration or exhausted resume budget fails the run with a recorded category.
The process can remain live when Ollama is unavailable; affected runs finish with a
`model_unavailable` failure.

LangGraph rebuilds only allow-listed classes from a checkpoint. Any other class is logged
("Deserializing unregistered type …") and comes back as raw data
([GHSA-g48c-2wqr-h844](https://github.com/advisories/GHSA-g48c-2wqr-h844)).

Changes on 2026-10-08:
- **One serializer everywhere.** Every checkpointer uses `checkpoint_serializer()`, with
  the allow-list in `runs/checkpointing.py`: production's PostgreSQL saver, the scripted
  regression, security and evaluation suites, and the tests. The scripted suites previously
  used LangGraph's default serializer, which only warned, so they did not restore
  checkpoints the way production does.
- **The allow-list is exactly the 11 types the run state can hold.** 13 types the state
  never held were removed; git history shows it never stored them.
- **A test keeps it that way:** `tests/test_checkpoint_allowlist.py` fails if a new state
  field type is missing from the list. A missing type would otherwise resume as raw data
  and fail the run later.

The pruning command permanently removes completed or failed runs older than the selected
age, including their stored run data and LangGraph checkpoints. Review and retain any run
needed for recovery or analysis before pruning. A project-wide disposable-run retention
period remains open; choose the age for the private local database deliberately. For example,
this removes terminal runs older than 30 days:

```bash
research-runs prune --older-than-days 30
```

## Phase 4 follow-up

The [Phase 3 evaluation report](../reference/phase-3-evaluation-report.md) records the
operational gate results and development-only answer measurements. Follow-up work should
review the original categorized timeout and checkpoint recovery, improve run-event logging
(the current JSON formatter omits run ID, mode, status, durations and usage fields), extend
the five scripted prompt-injection cases, and decide disposable run/checkpoint retention.
The evaluation showed limited answer coverage and one partially supported outcome on an
unsupported deep task in each sweep. These are diagnostic findings; Phase 3 gates passed,
and answer-quality thresholds remain open.

## Connect the host API and stop the service

The host Uvicorn API uses `http://127.0.0.1:11434` for the Ollama base URL. Keep the API
on the host Conda path described in the [Phase 2 search operations guide](phase-2-search.md);
the Compose API image does not contain PyTorch or the retrieval models.

Stop Ollama while retaining the imported models:

```bash
docker compose --profile llm stop ollama
```

Remove a model that is no longer needed, for example the 4B comparison model:

```bash
docker compose --profile llm exec ollama ollama rm qwen3.5-4b-text:q4_k_m
```

Remove the `ollama_models` volume only after stopping the service and confirming no other
models need it.
