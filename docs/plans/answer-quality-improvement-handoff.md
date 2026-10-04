# Answer-quality improvement — handoff

Created 2026-10-04 for a new session. Phase 3 is accepted; this is follow-up work that
changes an accepted decision, so it starts with an ADR and the owner's approval.

## Progress (2026-10-04)

The owner set precision over latency and accepted
[ADR-0025](../adr/0025-verified-quote-synthesis-with-thinking.md): synthesis thinks with no
output cap, prompt `p3-synthesize-v2` asks for quoted single-passage claims, table evidence
is shown as labeled rows, and code verification replaces the LLM judge. Implemented on
branch `answer-quality/verified-thinking-synthesis` with regression suite v2 and migration
017. Steps 1 to 3 and 5 below are done for these items; the owner directed the change
instead of a card review (step 4).

Still open: persisting dropped drafts and per-check results (design item 5), a verified
quote in place of a drifted claim (item 3, not adopted: drifted claims are dropped), the
`answered` definition (item 7, unchanged), the `deep_research` planner (item 8), and the
full live sweep with a repeated manual review (step 6). Private experiment material is under
`local-reference/phase3-runs/diagnostics/` and `answer-quality-live/`.

## Read first

1. `AGENTS.md` and the source of truth's change-control rule (section 1).
2. [Phase 3 answer-quality diagnosis](../research/phase-3-answer-quality-diagnosis.md): why only
   1 of 42 live runs was `answered`.
3. [ADR-0020](../adr/0020-phase3-evaluation-gates.md) decision 3 (the LLM support judge drops
   claims) and [ADR-0021](../adr/0021-phase3-qwen35-2b-gpu.md) (2B generator, output contracts).
4. Code: `src/research_platform/agents/answering.py` (`answer_question`, `check_handles`,
   `decide_outcome`), `agents/prompts.py` (`synthesize_messages`, `judge_messages`,
   `PROMPT_VERSIONS`), `agents/graph_deep.py`, `runs/repository.py`.
5. Private experiment material (ignored by Git, never copy its text into tracked files):
   `local-reference/phase3-runs/diagnostics/answer_quality_experiment.py`, its output
   `answer-quality-experiment.json`, and `judge-replay-claims.json`.

## What is known

**Not the cause:** context or token limits (prompts use at most about 8K of a 16K window;
all outputs were complete, valid JSON; a smaller evidence pack made the model decline more),
JSON output, or retrieval (all 10 tasks with Phase 2 judgments retrieved a relevant paper).

**The cause:** the 2B model's faithfulness at synthesis, and an unreliable LLM support judge.
The 2B judge drops supported claims and is inconsistent; the 4B model used as an offline
judge is too lenient. LLM judges cannot be the gate or the scorer.

**Offline experiment** (2026-10-04; 21 `quick` tasks; stored evidence replayed through the
2B generator; one replay, so treat as direction):

| Design | Runs declining | Claims kept | Runs with ≥1 kept claim | Kept-claim quality |
| --- | ---: | ---: | ---: | --- |
| A: current prompt + 2B judge over the whole pack | 11 | 10 | 10 | 4B judge: 6 supported, 2 partial, 2 unsupported |
| B: extractive prompt + 2B judge per claim, cited passages only | 8 | 36 | 11 judged good | 8 unsupported claims kept |
| C: extractive prompt + exact `quote` per claim, quote must exist in the cited passage | 6 | 40 | 13 | about 4 in 12 drift from their own quote |
| C + claim/quote content-word overlap ≥ 0.5 | 6 | 17 | 10 | 16 supported, 1 partial; matches a 12-claim manual review |

On the manual review, drifted claims had overlap 0.00–0.17 and faithful claims 0.59–1.00.

**New problem:** with the extractive prompt the model stops declining unanswerable
questions; it answered both no-evidence tasks with true but irrelevant facts (2 tasks only).

**Separate problem:** `deep_research` called only `search_papers` (42 of 42 calls in the
live sweep) and did no better than `quick`.

## Proposed design (for the ADR)

1. **Extractive synthesis, prompt `p3-synthesize-v2`.** Up to 6 claims; each is one short
   sentence stating a single fact from one passage, close to its wording, with no numbers,
   comparisons or qualifiers the passage does not state. Each claim carries `quote`: the
   exact sentence from the cited passage. Decline only if no passage is relevant.
   The experiment's prompt text is in `answer_quality_experiment.py` (`EXTRACTIVE`, `QUOTE`).
2. **Code-based verification replaces the LLM judge as the gate.** A claim is kept only if
   (a) its handles are known and packed (unchanged), (b) its quote is found in a cited
   passage after normalization, and (c) at least 50% of the claim's content words occur in
   the quote. Measure tolerant quote matching (for example ≥ 0.9 token-sequence similarity):
   strict matching dropped near-verbatim quotes that differed only in hyphenation.
3. **Owner decision: a drifted claim with a verified quote.** Either drop the claim, or
   present the verified quote itself as the claim. The second kept 40 verbatim claims in
   13 of 21 runs in the experiment.
4. **Relevance guard for unanswerable questions.** Design and measure options, for example a
   separate yes/no "does the evidence answer the question" call, or keeping the stricter
   decline instruction. Report false answers on the no-evidence tasks.
5. **Persist drafts and checks.** Store every drafted claim, its handles, quote, and each
   check's result, including dropped claims (new migration after `016`). Today only counts
   survive, which is why diagnosis needed replays.
6. **The LLM judge becomes optional and reported.** If kept, record its label as a signal;
   it never drops a claim. This changes ADR-0020 decision 3.
7. **`answered` definition.** Decide whether a run with kept claims and some dropped claims
   is `answered` with a dropped count, rather than `partially_supported`.
8. **`deep_research` tool choice (separate track).** Find why the native tool-call planner
   only picks `search_papers` (prompt, tool descriptions, or the model) before changing it.

## Steps

Each step ends at its completion criterion; stop and ask the owner where a step says so.

1. **Extend the offline experiment.** In `answer_quality_experiment.py`, add tolerant quote
   matching, the quote-as-claim option, and two or three relevance-guard options. Run it on
   both modes' stored evidence (all 42 runs) with at least two replays.
   *Done when* each variant has declines, kept claims, runs with ≥1 kept claim, and
   no-evidence-task false answers, per replay.
2. **Manually review a fixed sample.** Draw 40 kept claims from the best variant and 20 from
   the current design with a fixed random seed. Label each against its cited passage:
   supported, partial, unsupported, or irrelevant to the question. Store the labels
   privately; report counts only. Use assistant review and say so; it is not human review.
   *Done when* both samples are labeled and the precision difference is stated with its
   sample size.
3. **Write the ADR** (next free number in `docs/adr/`) with the design choices, the
   measured trade-offs, the open decisions in items 3, 4 and 7 above, and the change to
   ADR-0020. *Stop: the owner must approve it before any code change.*
4. **Write GitHub issue cards** following `docs/agents/issue-tracker.md` and the card style
   in `docs/plans/phase-3-agent-answers.md` (exact files, signatures, named tests, done
   criteria). Expected cards: synthesis v2 schema and prompt; code verification and outcome
   rules; draft persistence migration; relevance guard; regression-suite update;
   deep-planner investigation. *Done when* the owner has reviewed the cards.
5. **Implement through pull requests**, one card each, with CI green before merging.
   20 of the 28 scripted cases in `benchmarks/phase3/regression-cases-v1.json` include a
   judge reply; update them so they test the new gate, and keep the fabricated-handle and
   prompt-injection guarantees.
6. **Re-run the live development sweep** (P3-16 method, `scripts/phase3_dev_evaluation.py`)
   for both modes and repeat the step 2 manual review on the new outputs.
   *Done when* the evaluation report and the diagnosis note have a dated section comparing
   before and after, aggregates only.

## Rules

- Development data only: the 21 tasks in `local-reference/phase3-runs/dev-tasks-v1.json`.
  Read no held-out set, no `*origins.json`, and do not tune Phase 2 retrieval.
- Keep question text, claims, passages and per-run data under `local-reference/` and out of
  tracked files, logs, issues and pull requests. Do not work from `/tmp`; it is wiped on WSL
  restart.
- GPU: the 2B generator and Phase 2 retrieval share the 4 GB GPU. Offline replays need no
  retrieval, so the 4B model can run alone for comparisons; unload models between passes.
- Use the `sci_research_agent` Conda environment, run ruff, format, mypy and pytest before
  each pull request, and merge only with green CI.
