---
status: accepted
date: 2026-10-03
---

# Phase 3 generator: text-only Qwen3.5-2B Q4_K_M sharing the GPU with retrieval

Accepted by the project owner on 2026-10-03. This replaces ADR-0018 decision 1 (the model)
for Phase 3 and records the P3-04 fitness results that settle ADR-0018 decisions 3 to 5.
It supersedes the 2026-10-02 draft of this ADR, which chose the Ollama library 2B build
with retrieval on CPU from a harness later found to be unfair.

**Amended 2026-10-04 by [ADR-0025](0025-verified-quote-synthesis-with-thinking.md):** Decision 3 is amended: synthesis runs with thinking on and no output cap.

## Context

- **Layer placement, not model size, caused the first 4B failure.** Ollama's automatic fit
  put only 22–23 of 33 layers of the 4B on the GPU and left about 1 GB free, giving about
  1 token/second. `PARAMETER num_gpu 99` puts every layer on the GPU: 43.6 tokens/second
  at a 16K context.
- **GPU budget** (RTX 3050 Laptop, 4,096 MiB; Ollama sees about 3.2 GiB free):

  | Loaded on the GPU | GPU memory |
  | --- | ---: |
  | Phase 2 retrieval (gte + Ettin), idle / while reranking 16 long pairs | 713 / 1,361 MiB |
  | Qwen3.5-4B text-only `Q4_K_M`, all layers, 16K context | 3,343 MiB |
  | Qwen3.5-2B Ollama library build (`Q8_0`, includes vision) | 3,231 MiB |
  | Qwen3.5-2B text-only `Q4_K_M` + retrieval, reranking and generating at once | 2,934 MiB peak |

  Neither the 4B nor the library 2B fits beside retrieval.
- **Retrieval cannot move to CPU.** The same 16-pair rerank took 183–216 s on CPU against
  1.2 s on the GPU, which breaks the 300-second run budget.
- **The first fitness harness was unfair.** Thinking calls hit their output caps inside the
  thinking, JSON plan prompts did not list the tools, evidence handles were not constrained
  to the `E<number>` form, and an evaluation that was sufficient but also proposed actions
  was rejected. P3-04 fixed these in harness versions 2 to 4.

## Decision

1. **Model.** Qwen3.5-2B (Apache-2.0), text-only `Q4_K_M` GGUF from `unsloth/Qwen3.5-2B-GGUF`
   at revision `f6d5376be1edb4d416d56da11e5397a961aca8ae`, SHA-256
   `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223` (1,280,835,840 bytes).
   No vision projector is downloaded. It is imported into Ollama 0.35.0 as
   `qwen3.5-2b-text:q4_k_m` (digest `1157ab146135…`) with
   `configs/ollama/qwen3.5-2b-text.Modelfile`, which sets `num_gpu 99`.
2. **GPU sharing.** The generator and Phase 2 retrieval share the GPU; research runs keep
   `RESEARCH_PLATFORM_MODEL_DEVICE` at `auto` or `cuda`. A load that does not fit fails
   instead of splitting layers onto the CPU.
3. **Thinking.** On for planning, off for evaluate, synthesize and judge
   (`RESEARCH_PLATFORM_LLM_THINKING=plan`, the default). Thinking with JSON-constrained
   output ran 53–69 s per call and was valid in at most 33% of calls on every model.
4. **Planning format.** The planner uses native tool calls with thinking on. It is valid in
   100% of calls and correct in 83%, against 33% for the best JSON setting, which meets
   ADR-0018 decision 3. Code still validates every call as a typed `Action`. Evaluate,
   synthesize and judge stay on schema-constrained JSON. Card P3-19 adds the adapter method.
5. **Output contracts.** Evidence handles in model output schemas carry the pattern
   `^E[1-9][0-9]*$`, so constrained decoding can only emit valid handle forms.
   `SufficiencyDecision` ignores `next_actions` when `sufficient` is true.

## Fitness results (P3-04)

Synthetic set of 15 cases (6 plan, 3 evaluate, 3 synthesize, 3 judge), 16K context,
`num_gpu 99`, 100% GPU for every model. Thinking-off conditions ran 3 repetitions;
thinking-on conditions ran once without repair attempts. Thinking calls had 2,048 extra
output tokens.

**Selected model, harness 4, retrieval on the GPU** (peak 2,288 MiB during the run):

| Kind | Think | Format | Valid | Correct | Median / p95 |
| --- | --- | --- | ---: | ---: | ---: |
| Plan | on | native tools | 100% | 83.3% | 3.9 / 9.7 s |
| Plan | off | native tools | 83.3% | 83.3% | 0.9 / 1.4 s |
| Plan | off | JSON | 100% | 33.3% | 2.2 / 4.8 s |
| Plan | on | JSON | 0% | 0% | 58 / 59 s |
| Evaluate | off | JSON | 100% | 100% | 2.7 / 3.2 s |
| Evaluate | on | JSON | 33.3% | 33.3% | 53 / 54 s |
| Synthesize | off | JSON | 100% | 100% | 2.4 / 2.5 s |
| Synthesize | on | JSON | 0% | 0% | 69 / 69 s |
| Judge | off | JSON | 100% | 66.7% | 0.6 / 0.7 s |
| Judge | on | JSON | 33.3% | 0% | 55 / 55 s |

Every selected setting meets the P3-04 fit rules: at least 90% valid, p95 at most 45 s
(90 s for synthesis), and peak memory below 3,900 MiB.

**Comparison models, harness 3** (retrieval on CPU; no handle pattern or sufficiency fix),
best setting per kind, correct answers:

| Kind | Qwen3.5-4B text `Q4_K_M` | Qwen3.5-2B library `Q8_0` |
| --- | ---: | ---: |
| Plan (thinking on, native tools) | 100% | 83.3% |
| Evaluate (off, JSON) | 100% | 100% |
| Synthesize (off, JSON) | 33.3% | 33.3% |
| Judge (off, JSON) | 66.7% | 33.3% |
| Peak GPU memory | 3,343 MiB | 3,231 MiB |

On the selected model, the harness 4 fixes raised synthesis from 0% to 100% and evaluation
validity from 66.7% to 100%. The comparison models were not re-run with harness 4.

## Consequences

- The choice rests on fitting beside retrieval, not on answer quality. The 4B planned and
  judged better under harness 3; the 2B may give weaker answers, which P3-16 reports.
- The 2B generates about twice as fast as the 4B (about 82 tokens/second alone, 64 while
  reranking), which leaves headroom in the 300-second run budget.
- The 4B remains importable (`scripts/phase3_fetch_generator.sh 4b`) for comparison or a
  larger GPU; changing the model again needs an ADR.
- Cards P3-10, P3-11 and P3-14 change: native tool calls for the plan step, and the handle
  pattern in `DraftClaim`. P3-19 adds the adapter method first.
- The fitness set is small and synthetic; these numbers check fitness, not answer quality.

## Alternatives considered

- **Qwen3.5-4B with retrieval on CPU.** Rejected: CPU reranking breaks the run budget.
- **Qwen3.5-4B with automatic CPU/GPU layer split.** Rejected: about 1–14 tokens/second.
- **Ollama library `qwen3.5:2b`.** Rejected: it bundles vision weights in `Q8_0` and needs
  3,231 MiB, which does not fit beside retrieval.
- **Swapping models on and off the GPU per step.** Rejected: retrieval alone keeps 713 MiB
  resident, and reloading the generator costs seconds per call.
