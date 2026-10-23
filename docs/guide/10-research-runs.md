# 10. Research runs

A research run is one persisted execution of a question. This chapter explains what happens during a run and how to read its result. For the request and response format, see [HTTP API: research runs](04-http-api.md#research-runs).

## Modes

| | `quick` | `deep_research` |
| --- | --- | --- |
| Who decides the steps | Fixed code path | The model plans, code executes |
| Steps | `search_papers` (10 hits) → `search_evidence` within up to 5 candidates (20 results) → record relevant un-ingested papers → answer | `plan` → `execute` → (`wait_ingestion`) → `evaluate` → repeat or answer |
| Tools available | Search only | `search_papers`, `search_evidence`, `get_paper`, `get_citations`, `get_references`, `find_related_papers`, `discover_papers`, `request_ingestion` |
| Model calls | One synthesis (plus retries) | Plan and evaluate calls each round, then synthesis |
| Can add papers | No | Yes, if the caller's key has `ingest` |

Both graphs are LangGraph state machines ([`graph_quick.py`](../../src/research_platform/agents/graph_quick.py), [`graph_deep.py`](../../src/research_platform/agents/graph_deep.py)) with a PostgreSQL checkpointer, so a run survives a process restart.

### The deep-research loop

1. **Plan.** The model receives the question, filters, the tool definitions and observations so far, and proposes an *action batch*: a list of native tool calls. The first plan always includes searches.
2. **Execute.** Code validates every action against its typed schema and budget, then runs it. Identical repeated actions are served from a ledger rather than re-executed. Observations are compact and structured; large results are stored by reference.
3. **Wait for ingestion** (only if `request_ingestion` was accepted). The run enters `waiting_for_ingestion` and polls its request for up to 900 s, outside its active-time budget. When the worker publishes the next generation, the run switches to it once.
4. **Evaluate.** The model decides whether the evidence is sufficient and, if not, proposes the next actions.
5. Repeat until the evidence is sufficient, no actions remain, or a budget is exhausted; then **answer**.

Retrieved text is always treated as evidence, never as instructions. The model cannot raise budgets, choose arbitrary URLs, run SQL or touch files: tools expose only typed research operations.

## Budgets

Budgets are enforced in code, recorded in the run's provenance, and part of its configuration hash ([`RunBudgets`](../../src/research_platform/runs/contracts.py)).

| Budget | Default | Range | Limits |
| --- | --- | --- | --- |
| `max_plan_rounds` | 3 | 1–10 | Plan/evaluate rounds in `deep_research` |
| `max_actions_per_plan` | 4 | 1–10 | Tool calls in one action batch |
| `max_tool_calls` | 12 | 1–50 | Tool calls in the whole run |
| `max_citation_depth` | 2 | 0–3 | Hops of citation traversal |
| `max_evidence_passages` | 40 | 1–100 | Evidence handles (`E1`–`E40`) |
| `max_synthesis_tokens` | 8,000 | 500–32,000 | Evidence tokens packed into the synthesis prompt (half of it for evaluation prompts); the model's output is not capped |
| `max_model_retries` | 2 | 0–5 | Retries after invalid model output |
| `max_active_seconds` | 1,800 | up to 3,600 | Wall-clock time spent running |
| `max_resumes` | 2 | 0–5 | Restarts survived |
| `max_papers_per_wait` | 5 | 1–20 | Papers in one ingestion request |
| `max_ingestion_wait_seconds` | 900 | up to 3,600 | Time waiting for the worker |
| `max_synthesis_attempts` | 3 | 1–5 | Synthesis calls until one keeps a verified claim |

## Synthesis

The evidence gathered by the run is packed into the synthesis prompt under run-local handles. The model never sees chunk IDs, so it cannot invent a plausible-looking one. Tables appear as labelled rows, with every value next to its column header, so the model does not have to count columns.

The prompt (`p3-synthesize-v2`) puts the instructions and question before the evidence and asks for one quoted, single-passage claim per fact. Thinking is enabled with no output cap, a decision the owner made for precision over latency ([ADR-0025](../adr/0025-verified-quote-synthesis-with-thinking.md)). On an RTX 3050, synthesis takes a median of about 215 s, and a whole run takes 2 to 7 minutes.

The model returns schema-constrained JSON: an answer, a list of claims (handle, quote, text), and a flag for whether it judged the evidence insufficient. Invalid JSON is retried within `max_model_retries`. If no claim survives verification, synthesis is retried with the next seed, up to `max_synthesis_attempts`.

## Quote verification

Every drafted claim gets a verdict ([`verification.py`](../../src/research_platform/agents/verification.py)):

| Verdict | When |
| --- | --- |
| `unknown_handle` | The claim cites a handle that does not exist |
| `not_shown` | The handle exists but was not in the evidence shown to the model |
| `failed_checks` | One of the checks below failed |
| `kept_as_quote` | The claim text failed its checks but the quote passed, so the quote itself becomes the claim |
| `kept` | All checks passed |

The checks are:

- **`quote_found`**: the quote occurs in the cited passage after normalization. Table quotes must match exactly; prose quotes may differ slightly (token similarity at least 0.9), for example in hyphenation.
- **`words_from_quote`**: at least half of the claim's content words occur in the quote.
- **`numbers_from_quote`**: every number in the claim occurs in the quote.
- **`intensifiers_from_quote`**: words such as "significantly", "always", "only", "both", "all", "best" and "highest" appear in the claim only if they appear in the quote. This stops a single table row from becoming a claim about "both datasets" or "the highest score" ([ADR-0029](../adr/0029-claim-scope-words-and-prompt-trials.md)).
- **`no_handles_in_text`**: the claim text does not mention a handle such as `E7`.
- **`quote_names_its_row`** and **`no_other_row_named`**: for a table row, the quote includes the row's label, and the claim does not name another row the quote lacks.

All drafted claims, with their verdicts and failed checks, are stored. A reviewed sample showed the trade-off: the checks rejected 7 of 15 partial or unsupported claims, and 2 of 60 supported claims whose quotes were not copied exactly.

## Outcomes

| Outcome | Rule |
| --- | --- |
| `insufficient_evidence` | The model declared the evidence insufficient, or no claim was kept |
| `answered` | At least one claim kept, and every drafted claim was kept **as written** |
| `partially_supported` | Claims were kept, but at least one draft was rejected or kept only as its quote |

`answered` is deliberately strict. Its definition is still under review in [backlog #115](https://github.com/avsngh-git/RAGpipeline/issues/115).

## Failures

A run that cannot finish fails with one category:

| Category | Typical cause |
| --- | --- |
| `model_unavailable` | Ollama unreachable or killed |
| `invalid_model_output` | Output still invalid after the allowed retries |
| `budget_exhausted` | A run budget ran out before an answer |
| `timeout` | A call or the active-time budget timed out |
| `retrieval_error` | Search failed |
| `resume_exhausted` | The process restarted more than `max_resumes` times during the run |
| `configuration_changed` | The effective configuration differs from the one the run started with |
| `internal` | Anything else |

## Provenance and run records

The run view's `provenance` contains:

- `snapshot_id`, `generation` and `retrieval_profile_id`: which corpus and ranking were used;
- `configuration_id`: the `sha256` hash of the whole effective configuration;
- `code_revision`;
- `model`: name, quantization and runtime;
- `thinking`, `decoding` and `prompt_versions` with `prompt_fingerprints`;
- `tool_schema_digest`;
- `budgets`;
- `trace_id`;
- `reranker_runtime`: the device and precision the reranker actually used.

PostgreSQL also stores, per run: every tool call with validated arguments and returned IDs; every model call with its kind, options, token counts and duration (and its text, subject to retention); every drafted claim with its verdict; and a synthesis summary recording which handles the model judged relevant, which were packed or omitted, and whether it declared the evidence insufficient. These run records are what `research-runs explain` reads ([ADR-0026](../adr/0026-phase4-observability-and-run-records.md)).

## Uningested candidates

A run also lists `uningested_candidates`: relevant papers known only from metadata. They come from a similarity diagnostic with an uncalibrated threshold (0.5), so treat them as hints, not as evidence.

Next: [Evaluation](11-evaluation.md).
