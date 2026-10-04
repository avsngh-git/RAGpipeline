# Phase 3 answer-quality diagnosis

**Status:** assistant-reviewed, 2026-10-04. Diagnostic only: it changes no Phase 3 gate,
result or acceptance. It explains the answer-quality numbers in the
[Phase 3 evaluation report](../reference/phase-3-evaluation-report.md) and lists inputs for
Phase 4. All figures are aggregates; question text, claims, answers and passages stay under
ignored `local-reference/phase3-runs/`.

## Summary

The fully sampled sweep returned 1 `answered` outcome in 42 runs, and 23 runs ended
`insufficient_evidence`. The losses happen after retrieval, in the 2B generator's two
answer steps:

1. **Synthesis writes claims that go beyond their evidence.** It often attaches an
   invented qualifier to a correctly cited fact, or invents numbers. In 17 of 42 runs it
   declined to answer although relevant papers had been retrieved.
2. **The LLM support judge is inconsistent.** It drops clearly supported claims, labels
   partly supported claims `unsupported` instead of `partial`, and gives the same claim
   different labels when the inputs change slightly.
3. **The `answered` definition is strict.** One dropped claim makes a run
   `partially_supported`, so about 10 of 21 `quick` runs still returned at least one cited
   claim that survived the judge.

Neither JSON nor retrieval is the cause. Every synthesis and judge output parsed as valid
JSON, and every task with Phase 2 judgments retrieved a directly relevant paper.
Separately, `deep_research` used only `search_papers` and did no better than `quick`.

## Data and method

- **Sweep:** the fully sampled P3-16 sweep (`eval-issue17-measured-20261003T174822Z`),
  21 development tasks × 2 modes, `qwen3.5-2b-text:q4_k_m`, budgets and prompts as in the
  evaluation report.
- **Stored records:** final run views, `research_run_evidence` (passages a run collected)
  and `tool_calls` in `research_phase1_review`.
- **Replays:** the 21 `quick` runs re-run offline from their stored evidence with the
  production prompts and generator (`think` off, seed 20261001), varying one input at a
  time. Two replays were run.
- **Manual review:** 18 claims that a replay judge labelled `unsupported` were read beside
  their cited passages and judged by the assistant. This is assistant review, not human
  verification.

## Findings

### Where runs end

| Path (fully sampled sweep) | `quick` | `deep_research` |
| --- | ---: | ---: |
| `answered`: claims written, none dropped | 1 | 0 |
| `partially_supported`: at least one claim dropped by the judge | 9 | 9 |
| `insufficient_evidence`: the model declined to answer | 8 | 9 |
| `insufficient_evidence`: every claim dropped by the judge | 3 | 3 |
| Claims written / dropped as unsupported / kept | 39 / 24 / 15 | 30 / 18 / 12 |
| Claims rejected for an unknown handle | 0 | 0 |

### Retrieval is not the bottleneck

- Every run collected evidence: 8 to 40 passages (median 25 `quick`, 26 `deep_research`).
- In all 10 tasks that have Phase 2 paper judgments, both modes collected at least one
  passage from a paper judged directly relevant (label 2). About half of those runs still
  ended `insufficient_evidence`.

### Evidence and output format are not the bottleneck

| Collected evidence shape (42 runs) | Passages | Mean length |
| --- | ---: | ---: |
| Prose | 953 | 351 characters |
| Table rows as pipe-separated text | 65 | 722 characters |
| Table rows as prose | 4 | 1,282 characters |
| JSON-like text | 1 | 954 characters |

All synthesis and judge outputs in the sweep and in both replays were schema-valid JSON.
Two smaller format problems exist: some table passages are mostly empty `|` cells whose
values fall beyond the 2,000-character passage limit, and the model sometimes copies
fragments such as `-- handle: E1` into claim text.

### Replays

| Replay of the 21 `quick` runs | Replay 1 | Replay 2 |
| --- | ---: | ---: |
| Synthesis, 8,000-token pack: claims written / runs declining | 39 / 8 | 24 / 11 |
| Judge given the whole pack: supported / partial / unsupported | 12 / 3 / 24 | 8 / 2 / 14 |
| Judge given only the cited passages: supported / partial / unsupported | 9 / 8 / 22 | 9 / 4 / 11 |
| Synthesis, 3,000-token pack: claims written / runs declining | 15 / 14 | — |

- Replay 1 reproduced the production counts exactly (39 claims, 8 declines, 24 dropped).
  Replay 2 differed with the same seed, so generation is not fully repeatable.
- Giving the judge only the cited passages, as ADR-0020 intends, barely changes the drop
  rate. The current implementation sends the whole evidence pack; that design gap is
  real, but it is not the cause of the low numbers.
- A smaller evidence pack makes synthesis decline more often, so long context is not what
  makes the model give up.

### Manual review of judged-unsupported claims

| Assistant judgment of 18 claims | Claims |
| --- | ---: |
| Unsupported: invented numbers, contradicts the passage, or cites a title-only passage | 7 |
| Partly supported: a correct cited fact plus an invented qualifier; should be `partial` | 6 |
| Supported, some nearly verbatim; the judge was wrong | 4 |
| Unclear from the passage excerpt | 1 |

The two judge variants disagreed on 11 of the 18 claims. One near-verbatim claim was
labelled `unsupported` by both. The generator is most accurate when it copies a sentence
and least accurate when it paraphrases or combines facts.

### `deep_research` uses one tool

In the fully sampled sweep, all 42 `deep_research` tool calls were `search_papers`: no
`search_evidence`, citation or related-paper calls. Runs made 1 call (10 runs), 2 (5),
3 (3), 4 (2) or 5 (1). The plan fallback cannot explain this, because it also issues
`search_evidence`, so the native tool-call planner is choosing only paper search. Deep
outcomes were no better than `quick`.

## Phase 4 inputs

1. **Persist drafts and judgments.** Store each drafted claim, its cited handles, and the
   judge's label and reason, including dropped claims. Today only counts survive, which is
   why this diagnosis needed replays.
2. **Constrain synthesis.** Ask for short claims that state one fact from one passage,
   close to its wording, without added qualifiers or numbers that are not in the passage.
3. **Make the support check reliable.** Judge each claim against only its cited passages,
   treat `partial` and `unsupported` consistently, and add a second signal: a small NLI
   model, repeated judging, or a larger model if GPU memory allows.
4. **Revisit the outcome definition.** Decide whether `answered` should require zero
   dropped claims, or whether a run with supported claims and some dropped ones should
   count as answered with a dropped-claim count.
5. **Fix planner tool choice.** Find out why the native tool-call planner only calls
   `search_papers`: the plan prompt, the tool descriptions, or the 2B model.
6. **Render tables compactly.** Drop empty cells and keep headers with values so table
   evidence fits the passage limit.

## Limitations

21 development tasks, two replays of one mode, and 18 manually reviewed claims. Labels are
assistant judgments with source uncertainty. Generation is nondeterministic, so replay
counts vary by run. None of this is a held-out measurement, and none of it should be used
to tune Phase 2 retrieval.

## Follow-up experiments and decision (2026-10-04)

Offline replays of all 42 stored runs (both modes, one deterministic replay per variant)
and a blind assistant review of 75 kept claims led to
[ADR-0025](../adr/0025-verified-quote-synthesis-with-thinking.md), accepted by the owner,
who set precision over latency. Aggregates:

- **Prompt.** Putting instructions and the question before the evidence, describing every
  symbol and ordering the JSON fields as steps (quote before claim) made the model decline
  less (9 against 13 runs) but paraphrase more; one worked table example restored close
  copying (46 kept claims, 20 runs with a kept claim).
- **Tables.** Labeled table rows raised kept table claims from 0 to 9 without thinking and
  11 with thinking; without labels the model misread multi-level headers.
- **Thinking.** With no output cap every synthesis call stopped by itself (median 7,778
  thinking tokens, 215 s; maximum 14,394 tokens, 409 s). Kept claims that were supported
  and relevant rose from 50% (20 of 40 sampled) to 86% (30 of 35); relevance rose from 70%
  to 94%. Capped thinking had been cut off inside the reasoning.
- **Checks.** Quote verification in code dropped 7 of 15 partial or unsupported kept claims
  and 2 of 60 supported ones. The 4B model, used as a reference judge, called 8 of 12 bad
  claims supported.
- **Stopped experiment.** Thinking only to select passages, then extracting without
  thinking, was stopped after 4 runs at the owner's direction: selection thought as long as
  full synthesis (568 s against 587 s over three matched runs), so it saved no time.

Labels are assistant judgments, the samples are small (40 and 35 claims), and only 2 tasks
(4 runs) have no supporting evidence. None of this is a held-out measurement.
