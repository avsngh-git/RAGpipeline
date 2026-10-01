# Phase 3 local generator

This guide prepares the text-only Qwen3.5-4B Q4_K_M model for the Phase 3
research agent. Ollama runs in the optional Compose `llm` profile. The API
continues to run in the host Conda environment and reaches Ollama at
`http://127.0.0.1:11434`.

## Prerequisites

- Docker Desktop or Docker Engine with the NVIDIA Container Toolkit configured
  for the Docker daemon. Verify GPU access with `docker run --rm --gpus all
  nvidia/cuda:12.9.0-base-ubuntu22.04 nvidia-smi`.
- An NVIDIA GPU and driver compatible with the installed container runtime.
- WSL memory set to 12 GB (`%UserProfile%\\.wslconfig` on Windows).
- About 3 GB free for the GGUF, plus Docker image and Ollama model storage.

The Compose service pins `ollama/ollama:0.35.0` to multi-platform index digest
`sha256:2a6e883b917fc543389599dae79918f5cac9e1438890506982f44aa4f5625d01`.
The Linux AMD64 manifest is
`sha256:9c1dc45ea758396139ec0adfa52947714c61f8d1e4537a6e2daef8138e7a64a9`.
The index and manifest were checked on 2026-10-01 against the
[Ollama Docker Hub tag](https://hub.docker.com/layers/ollama/ollama/0.35.0/images/sha256-9c1dc45ea758396139ec0adfa52947714c61f8d1e4537a6e2daef8138e7a64a9).

The import source is
[`unsloth/Qwen3.5-4B-GGUF`](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF)
at revision `35edb278feb3f797d270a605d9745cab09538c12`. The file
`Qwen3.5-4B-Q4_K_M.gguf` is pinned to SHA-256
`00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4`.
The file is 2.74 GB and the script never requests an `mmproj` file. These
values were checked against the
[Hugging Face file record](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/blob/35edb278feb3f797d270a605d9745cab09538c12/Qwen3.5-4B-Q4_K_M.gguf).

## Fetch and start Ollama

From the repository root, fetch and verify the pinned GGUF. A valid existing
file is reused; a missing or invalid file is downloaded to a temporary file and
verified before it replaces the destination.

```bash
bash scripts/phase3_fetch_generator.sh
docker compose --profile llm up -d ollama
```

Compose keeps the existing default services unchanged. Without the `llm`
profile, `docker compose up` starts only PostgreSQL, Qdrant and the API. The
model directory is mounted read-only inside Ollama at `/models-import`; model
state is retained in the `ollama_models` named volume.

## Prepare the Modelfile and import

Pull the Ollama library model once as a reference, then capture its generated
Modelfile:

```bash
docker compose exec ollama ollama pull qwen3.5:4b-q4_K_M
docker compose exec ollama ollama show --modelfile qwen3.5:4b-q4_K_M
```

In `configs/ollama/qwen3.5-4b-text.Modelfile`, keep the local source line
`FROM /models-import/Qwen3.5-4B-Q4_K_M.gguf` and copy the `TEMPLATE`,
`RENDERER`, `PARSER`, `PARAMETER` and `LICENSE` directives from that output.
Then remove the larger library model and import the local text-only file:

```bash
docker compose exec ollama ollama rm qwen3.5:4b-q4_K_M
docker compose exec -T ollama ollama create qwen3.5-4b-text:q4_k_m -f /dev/stdin \
  < configs/ollama/qwen3.5-4b-text.Modelfile
```

The checked-in Modelfile was generated from `ollama show --modelfile` for the
reference model, retaining its `TEMPLATE`, `RENDERER`, `PARSER`, `PARAMETER`
and `LICENSE` directives and replacing only `FROM` with the mounted text-only
GGUF path.

## Smoke checks

Inspect the imported capabilities. The summary must include `thinking` and omit
`vision`:

```bash
docker compose exec ollama ollama show qwen3.5-4b-text:q4_k_m
```

Check thinking output:

```bash
curl --fail-with-body http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5-4b-text:q4_k_m","messages":[{"role":"user","content":"Think briefly, then answer: what is 2 + 2?"}],"think":true,"stream":false}'
```

Check schema-constrained JSON with thinking off and on:

```bash
curl --fail-with-body http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5-4b-text:q4_k_m","messages":[{"role":"user","content":"Return an answer to the question: what is 2 + 2?"}],"think":false,"stream":false,"format":{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}}'

curl --fail-with-body http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5-4b-text:q4_k_m","messages":[{"role":"user","content":"Think briefly and return an answer to the question: what is 2 + 2?"}],"think":true,"stream":false,"format":{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}}'
```

For both JSON calls, verify `message.content` parses as JSON with an `answer`
string. For the thinking call, also verify `message.thinking` is non-empty.

### Validation record

Validated on 2026-10-01 with Ollama 0.35.0 on an NVIDIA GeForce RTX 3050 Laptop
GPU (4096 MiB):

- Compose configuration validated with and without `--profile llm`; default
  mode contains only `postgres`, `qdrant` and `api`. The profiled Ollama service
  started successfully.
- `ollama show qwen3.5-4b-text:q4_k_m` reported `completion`, `tools` and
  `thinking` capabilities; it reported no `vision` capability.
- `/api/chat` with `think=true` returned a non-empty `message.thinking`.
- The schema-constrained JSON request parsed with an `answer` string for both
  `think=false` and `think=true`; the latter also returned non-empty thinking.
- GPU memory use was 0 MiB at idle and 2251 MiB with the model loaded and no
  other GPU workload. Ollama reported 35% CPU / 65% GPU processor placement.
- The pinned GGUF SHA-256 verified after download. A second fetch-script run
  verified the existing file and skipped downloading it.

## Connect the host API and stop the service

The host Uvicorn API uses `http://127.0.0.1:11434` for the Ollama base URL. Keep
the API on the host Conda path described in the
[Phase 2 search operations guide](phase-2-search.md); the Compose API image does
not contain PyTorch or the retrieval models.

Stop Ollama while retaining the imported model:

```bash
docker compose --profile llm stop ollama
```

Remove the imported text model when it is no longer needed:

```bash
docker compose --profile llm exec ollama ollama rm qwen3.5-4b-text:q4_k_m
```

The source GGUF stays under ignored `local-reference/phase3-models/`. To remove
Ollama's stored model layers as well, remove the `ollama_models` volume only
after stopping the service and confirming that no other models need it.
