# Phase 3 — Agent and structured answers

Status: accepted by the owner on 2026-10-03. All implementation and evaluation cards are
closed, including supplemental issues #30 and #31. P3-16 merged in PR #40 and its report
records the passing gates and diagnostic limits. P3-17 merged in PR #41; exact main CI
37144867835 passed on `f2cd0954a940d04c418d2607a98c79fc009b96be`. The [owner acceptance record](https://github.com/avsngh-git/RAGpipeline/issues/18#issuecomment-5972350487) records the owner's decision. ADR-0021 (2026-10-03) changed the generator and planning format after
P3-04.
Phase 2 is accepted ([ADR-0017](../adr/0017-phase2-accepted-profile-v10.md)) and its
retrieval profile v10 is frozen. This plan scopes Phase 3 of the
[source of truth](../agents/scientific-research-platform-source-of-truth.md) (section 21)
and splits it into task cards published as GitHub issues. The
[handoff](phase-3-agent-handoff.md) records progress.

## Goal and gate

Deliver the self-hosted model adapter, typed tools, a bounded LangGraph research workflow,
structured claim/evidence answers, citation verification, and tool-routing and end-to-end
evaluation.

**Gate** ([ADR-0020](../adr/0020-phase3-evaluation-gates.md)): on the development task set,
1. 100% of fabricated or unknown evidence handles are rejected (scripted cases);
2. at least 90% of live runs finish within budget;
3. every failed run carries a failure category;
4. all scripted tool-routing, budget, injection and resume cases pass in CI.

All operational gates passed. The recovered sweep completed 41/42 runs (quick 21/21,
deep 20/21; its one timeout had a failure category); the fully sampled measurement sweep
completed 42/42. Both had zero unknown live handles and no completed-run budget violations.
The exact gate evidence, reported answer-quality measurements, GPU use and limitations are
in the [Phase 3 evaluation report](../reference/phase-3-evaluation-report.md).
Answer-quality results remain diagnostic and do not block. No held-out set was built in
Phase 3. **The owner accepted Phase 3 on 2026-10-03** ([owner acceptance record](https://github.com/avsngh-git/RAGpipeline/issues/18#issuecomment-5972350487)).

## Decisions

| Topic | Decision | Record |
| --- | --- | --- |
| Generator | Text-only Qwen3.5-2B `Q4_K_M` GGUF as `qwen3.5-2b-text:q4_k_m`, all layers on the GPU (`num_gpu 99`) | [ADR-0021](../adr/0021-phase3-qwen35-2b-gpu.md) |
| Serving | Ollama as a Compose service (profile `llm`, GPU); our own `httpx` adapter; no Qwen-Agent | ADR-0018 |
| GPU sharing | Generator and Phase 2 retrieval share the GPU (2,934 MiB peak). The 4B does not fit beside retrieval; CPU reranking takes minutes per search | ADR-0021 |
| Model output | Native tool calls with thinking on for planning (P3-19); schema-constrained JSON for evaluate, synthesize and judge. Handles in schemas carry the pattern `^E[1-9][0-9]*$` | ADR-0018, ADR-0021 |
| Thinking | On for planning only (`RESEARCH_PLATFORM_LLM_THINKING=plan`); thinking with JSON output is slow and mostly invalid | ADR-0021 |
| Orchestration | LangGraph, one agent. `quick` is a fixed graph built first; `deep_research` plans, executes, then judges sufficiency and re-plans | [ADR-0019](../adr/0019-phase3-research-run-execution.md) |
| Run execution | `POST /v1/research` queues; one in-process asyncio worker runs one run at a time | ADR-0019 |
| Durability | LangGraph `AsyncPostgresSaver` in the Postgres schema `langgraph`, sync durability, strict msgpack; automatic resume on startup with at most 2 resumes, refused after a configuration change | ADR-0019 |
| Evidence citing | The model cites `E1`…`E40` handles; code maps handles to `chunk_id`; an unknown handle is a verification failure | ADR-0019 |
| Support check | One LLM judge call per answer labels each claim `supported`, `partial` or `unsupported`; unsupported claims are dropped | ADR-0020 |
| Evaluation | Operational gates above; 21 development tasks, one per surviving Phase 2 development family; CI uses a scripted fake LLM only | ADR-0020 |
| Deferred | Langfuse, authentication, rate limits, MCP and UI belong to later phases. Phase 3 includes 5 prompt-injection cases | this plan |

Default run budgets, which live in code (P3-05) and are recorded with every run: 3 plan
rounds; 4 actions per plan; 12 tool calls per run; identical calls served from cache;
citation depth 2; 40 evidence passages; 8,000 synthesis tokens; 2 model retries per call;
300 seconds of active time; 2 resumes.

## Architecture

```text
POST /v1/research ─► RunExecutor (one asyncio worker) ─► LangGraph graph (quick | deep_research)
                                                             │  checkpoints: langgraph schema
                       nodes call ──► ResearchTools ──► Phase2APIServices (search, papers, citations)
                                  │                 └─► RelatedPaperReader (new, SQL)
                                  ├─► LLMClient (OllamaClient | ScriptedLLM)
                                  └─► RunRepository (research_runs, tool_calls, claims, evidence)
```

New packages, following section 19 of the source of truth:

| Package | Contents | Cards |
| --- | --- | --- |
| `src/research_platform/llm/` | `LLMClient` protocol, `OllamaClient`, `ScriptedLLM` | P3-03 |
| `src/research_platform/runs/` | run contracts, repository, checkpointer, executor | P3-05, P3-06, P3-07, P3-13 |
| `src/research_platform/tools/` | the six typed research tools and their budget guard | P3-09 |
| `src/research_platform/agents/` | actions, state, evidence registry, prompts, answering, graphs | P3-05, P3-10, P3-11, P3-12, P3-14 |
| `src/research_platform/search/paper_related.py` | `find_related_papers` SQL service | P3-08 |

Layering rules: graph nodes call tools, the LLM client and the repository; only
repositories and search services contain SQL; routes map HTTP to the executor.
Retrieved text is evidence, never instruction: prompts wrap it in `<evidence>` blocks and
the system prompt says so (P3-10).

## Module map

Each card is one GitHub issue under the map issue, sized for one session (about 300 to
600 changed lines). "Blocked by" lists cards that must be merged first.

| Card | Module | Blocked by | Label |
| --- | --- | --- | --- |
| P3-01 | ADRs, source-of-truth update, plan and handoff (this change set) | none | done by planner |
| P3-02 | Ollama Compose service and text-only GGUF import script | P3-01 | ready-for-agent |
| P3-03 | LLM adapter: protocol, Ollama client, scripted fake, settings | P3-05 | ready-for-human (owner writes, tutored) |
| P3-04 | Generator fitness check and ADR-0018 results | P3-02, P3-03 | ready-for-agent |
| P3-05 | Run contracts, actions and budgets | P3-01 | ready-for-agent |
| P3-06 | Migration 016 and run repository | P3-05 | ready-for-agent |
| P3-07 | Dependencies, LangGraph checkpointer and prune command | P3-01 | ready-for-agent |
| P3-08 | `find_related_papers` service | none | ready-for-agent |
| P3-09 | Typed research tools and budget guard | P3-05, P3-08 | ready-for-agent |
| P3-10 | Evidence registry, packing and versioned prompts | P3-03, P3-05, P3-09 | ready-for-agent |
| P3-11 | Answer synthesis and citation verification | P3-03, P3-10 | ready-for-agent |
| P3-12 | `quick` graph and run lifecycle | P3-06, P3-07, P3-09, P3-11 | ready-for-human (pair, step by step) |
| P3-13 | Research API, run executor and startup resume | P3-12, P3-18 | ready-for-agent |
| P3-14 | `deep_research` graph | P3-12, P3-13, P3-19 | ready-for-human (pair, step by step) |
| P3-15 | CI regression suite on the scripted LLM | P3-13, P3-14, P3-19 | ready-for-agent |
| P3-16 | Live development evaluation and report | P3-04, P3-14 | ready-for-agent |
| P3-17 | Phase 3 closeout | P3-15, P3-16 | done; owner accepted Phase 3 on 2026-10-03 ([owner acceptance record](https://github.com/avsngh-git/RAGpipeline/issues/18#issuecomment-5972350487)) |
| P3-18 | Copy the gte dense index into the main stack so profile v10 serves | none | ready-for-agent |
| P3-19 | Native tool-call planning in the LLM adapter | P3-04 | ready-for-agent |

Parallel start: P3-02, P3-05, P3-07 and P3-08 have no open blockers once this change set
is merged; P3-03 follows P3-05.

## Card rules

Every card points here. These rules apply to every implementer.

1. **Scope.** Read the card, the files it names and this section. Touch only the files the
   card lists; when another file must change, stop and ask in the issue.
2. **Branch.** Work on `phase3/p3-NN-short-name` from current `main`, and open one pull
   request per card with `Closes #<issue>` in the body.
3. **Interfaces.** Implement the signatures in the card exactly; names, fields and enum
   values are shared with other cards. When a signature seems wrong, comment on the issue
   instead of changing it.
4. **Style.** Match the surrounding code: frozen dataclasses or Pydantic models with
   validation in `__post_init__` or validators, type hints that pass `mypy --strict`, short
   docstrings, no comments that narrate the code.
5. **Tests.** Write every test the card names, in the file it names. Offline tests use the
   scripted LLM and fakes; PostgreSQL tests follow `tests/integration/test_paper_graph.py`
   (the `integration` marker, skipped without `RESEARCH_PLATFORM_TEST_DATABASE_URL`,
   database `research_test`).
6. **Checks.** Before opening the pull request, run in the `sci_research_agent` Conda
   environment and paste the summary lines into the pull request:
   ```bash
   python -m ruff check .
   python -m ruff format --check .
   python -m mypy
   python -m pytest
   ```
   Hosted CI must be green before review.
7. **Dependencies.** Add only the dependencies a card names, with the pins it names.
8. **Data.** Keep private inputs and outputs under `local-reference/` (ignored by Git).
   Never write evaluation data, question text or passages into tracked files, logs or
   issues; `/tmp` is not persistent on this machine.
9. **Done.** A card is done when every item in its "Done when" list is checked in the
   pull request description.

## Risks and fallbacks

| Risk | Detection | Response |
| --- | --- | --- |
| Generator and retrieval exceed GPU memory | Ollama load fails with `num_gpu 99`; P3-04 memory probe | Measured headroom: 2,934 MiB peak of about 3.2 GiB free. Lower `OLLAMA_CONTEXT_LENGTH`; any model change needs an ADR (ADR-0021) |
| The 2B answers poorly | P3-16 reported quality numbers | Reported, not gated (ADR-0020); the 4B stays importable for a larger GPU |
| Native tool calls fail on a plan | `call_tools` raises `LLMInvalidOutput` | P3-14 falls back to the default `quick` actions |
| Live searches fail on the main stack | `SnapshotIndexNotReady` | P3-18 copies the gte index from the eval stack |
| Few stored in-corpus citation edges | P3-08 returns empty pages | An empty result is a valid observation; the agent continues |
| A resumed run differs from an uninterrupted one | P3-15 resume case | Accepted: model calls are nondeterministic; provenance records each resume |

## Not in Phase 3

Langfuse traces, authentication, rate limiting, MCP, a UI, a held-out answer benchmark,
retrieval-profile changes, and answer-quality gates. Phase 4 consumes the reported quality
numbers and the stored checkpoints.
