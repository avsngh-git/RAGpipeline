---
status: accepted
date: 2026-10-01
---

# Phase 3 local generator, serving and model-output format

Accepted by the project owner on 2026-10-01. This resolves open decisions 6 (generator,
quantization, serving) of the source of truth for Phase 3. The fitness results in the
last section are recorded by card P3-04 and may trigger the fallbacks below without a new
ADR. Any other change needs one.

## Context

- The laptop GPU is an RTX 3050 with 4 GB. The Phase 2 profile v10 (gte-modernbert-base +
  Ettin-150M) allocates about 0.63 GB of CUDA memory. WSL is raised to 12 GB of RAM.
- The Ollama library build `qwen3.5:4b-q4_K_M` is 3.4 GB because it bundles the vision
  encoder. The unsloth GGUF release splits the text model (`Qwen3.5-4B-Q4_K_M.gguf`,
  2.74 GB) from the vision projector (`mmproj-*.gguf`, about 0.67 GB). Phase 3 uses text
  only.
- Ollama 0.17 could not load Hugging Face Qwen3.5 GGUFs with a separate projector; users
  reported that the text-only file loads. Ollama is at 0.35 as of this decision.
- Small quantized models emit malformed native tool calls more often than larger ones.
  Ollama parses tool calls after generation, while its `format` option constrains
  generation to a JSON schema.
- The source of truth locks LangGraph for orchestration and requires a replaceable model
  adapter (sections 6.1 and 12.2).

## Decision

1. **Model** (replaced for Phase 3 by [ADR-0021](0021-phase3-qwen35-2b-gpu.md)). Qwen3.5-4B (Apache-2.0), text-only `Q4_K_M` GGUF from
   `unsloth/Qwen3.5-4B-GGUF`, pinned by file SHA-256, imported into Ollama with a Modelfile
   under the local name `qwen3.5-4b-text:q4_k_m`. The vision projector is never loaded.
2. **Serving.** Ollama runs as a Compose service in the `llm` profile with the GPU and a
   pinned image tag, bound to `127.0.0.1:11434`. The application calls Ollama's
   `/api/chat` through its own `httpx` adapter (`research_platform.llm`). No vendor SDK
   and no Qwen-Agent: LangGraph owns the agent loop.
3. **Output format.** Every model call is schema-constrained JSON (`format` set to the
   Pydantic model's JSON schema) and is validated with Pydantic, with at most 2 repair
   retries. P3-04 also measures native tool calling on the same planning cases; the
   planner switches to native calls only if its routing accuracy is at least 10 points
   higher at equal or better output validity. The planner's `ActionBatch` interface stays
   the same either way.
4. **Thinking.** P3-04 measures thinking on and off for each call kind (plan, evaluate,
   synthesize, judge). The default for each call kind is the better-scoring setting, with
   ties broken by lower latency. The setting is recorded in run provenance.
5. **Fallbacks, in order,** each tried only when the previous one fails P3-04:
   1. generator and retrieval both on the GPU, context about 16K tokens (reduce context or
      use 8-bit KV cache before moving on);
   2. retrieval on CPU during research runs (`RESEARCH_PLATFORM_MODEL_DEVICE=cpu`);
   3. the llama.cpp server for the same GGUF, behind the same adapter protocol;
   4. `qwen3.5:2b`.

## Consequences

- Run provenance records the model name, the GGUF SHA-256, the Ollama version, the context
  size, thinking settings and decoding options.
- Generation and Phase 2 retrieval share 4 GB; fallback 2 slows retrieval, which runs
  inside research runs and is not interactive search.
- CI never needs Ollama: tests use `ScriptedLLM`.
- Phase 3 answers depend on one small model; generator quality is reported, not gated.

## Alternatives considered

- **Ollama library build with vision (3.4 GB).** Leaves too little GPU memory beside
  retrieval.
- **Qwen-Agent.** Duplicates LangGraph's loop and its value is native function-call
  handling, which this design does not use by default.
- **Native tool calling by default.** Less reliable output on a 4B quantized model; kept as
  a measured alternative.
- **A model bake-off.** The owner chose the model; P3-04 checks fitness only.

## Fitness results (P3-04)

Measured 2026-10-02 to 2026-10-03; the full tables are in
[ADR-0021](0021-phase3-qwen35-2b-gpu.md).

- Ollama's automatic layer fit left part of the 4B on the CPU (about 1 token/second);
  `num_gpu 99` fixes this (43.6 tokens/second for the 4B).
- Fallback step 1 (generator and retrieval together on the GPU) fails for the 4B: it needs
  3,343 MiB, and retrieval peaks at 1,361 MiB. Step 2 (retrieval on CPU) also fails: a
  16-pair rerank takes 183–216 s on CPU against 1.2 s on the GPU.
- Under the owner's direction, ADR-0021 replaces decision 1 with the text-only Qwen3.5-2B
  `Q4_K_M`, which shares the GPU with retrieval (2,934 MiB peak) and passes every fit rule.
- Decision 3: native tool calls with thinking on plan best (100% valid, 83% correct against
  33% for the best JSON setting), so the planner uses them; other call kinds stay on JSON.
- Decision 4: thinking is on for planning only. Thinking with JSON output ran 53–69 s per
  call and was valid in at most 33% of calls.
