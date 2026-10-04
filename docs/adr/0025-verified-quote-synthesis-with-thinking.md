---
status: accepted
date: 2026-10-04
---

# Answer synthesis: thinking, quoted claims, labeled tables and code verification

Accepted by the project owner on 2026-10-04 after the answer-quality experiments below.
The owner set precision, not latency, as the goal: answers on this laptop are allowed to
take minutes. This replaces ADR-0020 decision 3 (the LLM support judge drops claims) and
ADR-0021 decision 3 for the synthesize step (thinking off). It does not change any Phase 2
or Phase 3 gate.

## Context

- The Phase 3 sweep returned 1 `answered` run in 42. Retrieval found a directly relevant
  paper for every judged task; the losses came from the 2B generator adding facts its
  passages do not state, and from the 2B support judge, which dropped supported claims and
  labelled the same claim differently on reruns
  ([diagnosis](../research/phase-3-answer-quality-diagnosis.md)).
- Table evidence reached the model as pipe-separated rows several lines below their
  headers. With two-level headers the model could not tell which value belonged to which
  column, and copied rows were misdescribed.
- Offline replays of the 42 stored runs (21 development tasks, both modes; one
  deterministic replay per variant, 2B generator, 4B model as a lenient reference label)
  compared prompt, table and thinking variants:

  | Variant | Declined | Kept claims | Runs with a kept claim | No-evidence runs declined |
  | --- | ---: | ---: | ---: | ---: |
  | Earlier quote prompt, thinking off | 13 | 46 | 19 | 2 of 4 |
  | Step-by-step prompt, raw tables, thinking off | 9 | 19 | 14 | 2 of 4 |
  | Step-by-step prompt, labeled tables, no table example, thinking off | 16 | 30 | 15 | 3 of 4 |
  | Step-by-step prompt, labeled tables and example, thinking off | 14 | 46 | 20 | 4 of 4 |
  | Same, thinking on with no output cap | 16 | 35 | 18 | 4 of 4 |

  Claims citing a table and kept: 0 with raw tables, 9 with labeled tables, 11 with labeled
  tables and thinking.
- A blind assistant review (not human review) labelled 40 sampled kept claims without
  thinking and all 35 kept claims with thinking against their cited passage and question:

  | Kept claims | Thinking off | Thinking on |
  | --- | ---: | ---: |
  | Supported | 72% (29 of 40) | 89% (31 of 35) |
  | Relevant to the question | 70% | 94% |
  | Supported and relevant | 50% | 86% |
  | Runs with a supported, relevant claim | 11 to 14 of 42 | 17 of 42 |

  Thinking mostly improved the choice of passage: without it, true claims from the wrong
  paper, a reference-list entry or the wrong table were kept. The 4B reference label
  called 8 of the 12 partial or unsupported claims supported and does not judge relevance.
- With thinking and no cap, every one of the 42 synthesis calls stopped by itself: median
  7,778 thinking tokens (maximum 14,394), median 215 s per call (maximum 409 s). Five calls
  alone exceeded the former 300 s run budget. With a 16K window, capped calls had been cut
  off inside the thinking.
- A two-call design that thought only about which passages to use was stopped after 4
  runs at the owner's direction: selection alone thought as long as full synthesis
  (6,447 to 10,431 tokens; 568 s against 587 s over three matched runs).

## Decision

1. **Thinking for synthesis.** Synthesis runs with thinking on and no output-token cap
   (`max_output_tokens=None`, sent to Ollama as `num_predict: -1`). Defaults change to
   `RESEARCH_PLATFORM_LLM_THINKING=plan,synthesize`, a 32,768-token context, a 1,200 s
   per-call timeout (validated up to 3,600 s) and a 1,800 s run budget
   (`max_active_seconds`). Each call is bounded by the timeout and the run budget, not by
   a token count. Planning keeps thinking; evaluation keeps it off.
2. **Prompt `p3-synthesize-v2`.** Instructions and the question come before the evidence.
   The prompt describes the input and every symbol: the evidence tags and attributes, `…`
   for a cut passage, labeled table rows, group lines, and the papers' own bracketed
   references, which are not handles. Its numbered steps follow the JSON fields, which are
   all required and written in this order: `relevant_handles`, `insufficient_evidence`,
   `claims` (each `handle`, then `quote`, then `text`), `answer`. It shows one worked prose
   example and one table example. Each claim cites one passage. The tested wording asked for
   "the part of one Row line"; the shipped wording asks for the Row line from its start so
   that the row's name is in the quote, matching check 4 below. That wording change has
   not been measured on its own.
3. **Labeled table rows.** Table hits are rendered from their structured table context as
   `Row: Method: SparseX; Dataset A — mAP: 31.0, nDCG@10: 52.0`: each value carries its
   header path, including merged group headers and header references that point away
   from the cell's column, and a row with only a first-column value becomes
   `Group: name`. Hits that select segments of one long cell keep their indexed text.
   Table passages are cut at 8,000 characters instead of the 2,000 used for prose. The
   rendered text is what the model sees, what the run stores and what verification reads.
   On the 50 table passages of the sweep, 38 render as in the experiment, 11 render
   better, and 1 loses a merged label whose first row precedes the passage.
4. **Quote verification replaces the support judge as the gate.** A claim is kept only if
   its handle was registered and shown to the model and all of these hold against its
   cited passage: the quote occurs in it after normalization (exactly for table rows;
   prose may differ by hyphenation or a word, at 0.9 token similarity); at least half of
   the claim's content words occur in the quote; every number and every intensifier
   (`significantly`, `consistently`, `always`, ...) in the claim occurs in the quote; the
   claim text contains no handle; and for a table row the quote contains the row's label
   and the claim names no other row the quote lacks. On the 75 reviewed claims these
   checks dropped 7 of 15 partial or unsupported claims and 2 of 60 supported ones (both
   with non-verbatim quotes), raising supported-and-relevant kept claims to 59% without
   thinking and 88% with it. No judge call is made.
5. **Stored and returned claims.** A kept claim is recorded as `supported`, meaning it
   passed quote verification, and carries its quote (`ClaimResult.quote`, migration 017).
   Claims from earlier runs keep their judge labels and no quote. The answer text lists
   only verified claims with their handles; the model's own summary is not verified and
   is not shown.
6. **Counts and outcomes.** `rejected_claims` counts unknown or unshown handles and
   `unsupported_claims` counts claims that failed verification. The `answered`,
   `partially_supported` and `insufficient_evidence` rules are unchanged.
7. **Regression suite v2.** `benchmarks/phase3/regression-cases-v2.json` scripts quoted
   claims and no judge, keeps the fabricated-handle and prompt-injection guarantees, and
   adds five `claim_verification` cases (33 in total). Version 1 is kept as the Phase 3
   acceptance record.

## Consequences

- Answers are slower: synthesis takes about 2 to 7 minutes per run on the RTX 3050, and
  a run may take up to 30 minutes before it fails with a budget category.
- Precision rises at the cost of recall: faithful paraphrases that drift from their quote
  are dropped, and fewer claims are kept per run.
- String checks do not catch every meaning error. In the review, 3 of 32 kept claims with
  thinking were still partial or unsupported (a changed role, a hedge turned into a
  certainty, a wrong count).
- The 2B model and Phase 2 retrieval still share the GPU; the 32K window adds about
  0.2 GB to the generator.
- CI stays model-free: the scripted suite exercises the new schema and checks.
- Not decided here: storing dropped drafts and per-check results, using a verified quote
  in place of a drifted claim, revising the `answered` definition, and the
  `deep_research` planner calling only `search_papers`.

## Alternatives considered

- **Keep the 2B support judge, or use the 4B as judge.** Rejected: the 2B was inconsistent
  and the 4B called most bad claims supported.
- **Thinking off.** Rejected by the owner for precision: 50% against 86% supported and
  relevant kept claims.
- **Capped or selection-only thinking.** Rejected: capped calls were cut off inside the
  thinking, and selection-only thinking was not faster.
- **A small NLI model as a second check.** Not needed for this decision; it remains an
  option for the meaning errors string checks miss.
