---
status: accepted
date: 2026-10-11
---

# Scope words in claim verification, and two prompt trials not adopted

Requested by the project owner on 2026-10-10 after a review of the model's thinking, and
accepted by the owner on 2026-10-11. This
amends decision 4 of [ADR-0025](0025-verified-quote-synthesis-with-thinking.md) (the words
a claim may use only if its quote does). Prompts, the six-claim limit, outcome rules,
thinking settings and budgets are unchanged.

## Context

- The assistant read 218 stored model calls whose thinking text was kept in the JSONL
  traces (`local-reference/traces/`, sweeps of 2026-10-07 and 2026-10-08: 131 synthesis,
  35 evaluate and 52 plan calls). Traces, replays and review notes are private under
  `local-reference/phase4/cot-review-2026-10-10/`. Counts come from pattern matching and
  include repeated questions, so they are approximate.
- The traces showed four patterns:
  - **Abstention:** 57 of 131 synthesis calls set `insufficient_evidence`, while the
    2026-10-09 source review labelled none of 69 reviewed contexts insufficient. The model
    tied relevance to the most literal part of a question and refused table comparisons.
  - **Narrow output:** a median of 2 cited passages and 2 to 3 claims per answered call.
  - **Invisible output format:** the schema reached Ollama only as the `format` grammar.
    86 synthesis traces debated field names; about 10% of synthesis and 27% of evaluation
    thinking lines were about the format.
  - **Skimming:** 88 traces grouped passages into guessed handle ranges.
- **Two prompt trials.** Each was replayed on stored inputs for the 21 development
  questions (the first stored input per question, one sample each, 32K context,
  production sampling and seed). Old and new drafts were scored by the same checks, with
  assistant review of support and relevance:

  | Prompt | Kept claims | Supported and relevant | Abstained |
  | --- | ---: | ---: | ---: |
  | `p3-synthesize-v2` (stored outputs) | 28 | about 24 (86%) | 8 |
  | Broad: answer every part, abstain only if no part is answered, 12 claims, one claim per compared row | 33 | about 24 (73%) | 8 |
  | Format only: v2 plus the visible JSON format and no `Group` line in quotes | 20 | about 16 (80%) | 9 |

  The broad prompt added scope words taken from single table rows ("on both datasets",
  "the highest mAP") and cited off-topic passages for multi-part questions. Neither trial
  reduced abstention. Visible formats stopped the format debate (0 of 21 traces) but did
  not shorten thinking (median 31,700 characters). The same questions flipped between
  answering and abstaining across runs with nearly identical prompts, so single-sample
  replays cannot detect small effects. Both measured patches are kept privately under
  `replay/`.
- **Scope words passed verification.** `verify_claim` checked "every", "always",
  "significantly" and similar words, but not "both", "all", "best" or "highest". A test
  allowed superlatives to paraphrase; no recorded reason was found for that choice.

## Decision

1. **Scope and superlative words.** A claim may use "both", "all", "best", "highest",
   "lowest", "worst", "largest" or "smallest" only if its quote does, in addition to the
   ADR-0025 list. The check keeps its name, `intensifiers_from_quote`.
2. **Prompts unchanged.** Neither trial is adopted: neither reduced abstention, and the
   broad prompt lowered reviewed precision.

## Evidence for decision 1

- Of 59 distinct historical drafts that passed verification, the extra words reject 2. One
  claimed "the highest mAP" from a single table row. The other paraphrased "both"
  faithfully; its quote alone passes, so quote fallback keeps it as a quoted claim.
- In the broad-prompt replay, the three claims with "on both datasets" or "highest" taken
  from one row are now shown as their quoted rows instead.

## Consequences

- Fewer claims carry scope or ranking words their quote lacks. A faithful paraphrase that
  adds "both" or "best" is shown as its quote instead.
- The same words apply to labelled commentary (`supported_by`): a model-written answer
  sentence using one of them is shown only if a kept quote contains it.
- Abstention on multi-part, "does any paper" and table-comparison questions remains open.
  A further prompt change needs a paired measurement with several seeds per question
  (about 126 synthesis calls, roughly 8 hours on the RTX 3050).
- Prompt versions and fingerprints do not change; the code revision does.

## Alternatives considered

- **Adopt the broad prompt.** Rejected: more claims, lower reviewed precision, no fewer
  abstentions.
- **Adopt the format-only prompt.** Rejected: fewer kept claims in the replay and no
  measured benefit besides the format debate.
- **Verify claims drafted beside a declared insufficiency.** Not needed now: with
  `p3-synthesize-v2`, none of 57 flagged drafts contained claims.
- **A larger model.** Out of scope: ADR-0021 records that the 4B model does not fit beside
  retrieval on the 4 GiB GPU.
