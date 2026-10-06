# Phase 3.5 online ingestion evaluation (Gate D)

**Status:** assistant-reviewed, 2026-10-05. Card P35-29
([#73](https://github.com/avsngh-git/RAGpipeline/issues/73)). Development-only; answer
quality is reported, not gated.

**Wait-cap gate: pass** (9 of 9 ingestion-triggering runs within the cap, forced-trigger
pass; not measurable in the natural pass, where the model never triggered ingestion).
**Failure-category gate: pass** (no run failed in either pass). **Scripted CI cases:** all
seven pass locally and in hosted CI run
[37361270869](https://github.com/avsngh-git/RAGpipeline/actions/runs/37361270869) on `faad169`.

Question text, answers, run views and per-run records stay under ignored
`local-reference/phase35/live/`; this report holds aggregates only.

## Run record

| Field | Value |
| --- | --- |
| Date | 2026-10-05 |
| Code revision | `475f090` plus the uncommitted P35-29 files, committed with this report |
| Corpus | Leave-out corpus: collection `leave-out-dev`, published generation 2 (93 + 1 papers; 6 of 7 hidden papers still hidden) |
| Families | The 10 leave-out development families (development tasks with direct-evidence paper judgments) |
| Mode and budgets | `deep_research`, default budgets (12 tool calls, 5 papers per wait, 900 s wait cap, 1,800 s active time) |
| Generator | Ollama `qwen3.5-2b-text:q4_k_m`, settings as served (ADR-0021, ADR-0025) |
| Services | Host API and `research-worker` (`online` handler) in `sci_research_agent`; Qdrant v1.19.1; RTX 3050 Laptop (4 GB) |
| Script | [`scripts/phase35_live_evaluation.py`](../../scripts/phase35_live_evaluation.py) |

## Scripted CI cases

[`tests/test_phase35_regression.py`](../../tests/test_phase35_regression.py) and
[`phase35_regression.py`](../../src/research_platform/evaluation/phase35_regression.py):

| # | Case | Result |
| --- | --- | --- |
| 1 | `request_ingestion` for a paper without a permitted route ends `metadata_only`; the run completes on the old generation | pass |
| 2 | The per-run paper limit (`run_paper_limit`) and the daily spend cap (`discovery_budget`) refuse with recorded reasons | pass |
| 3 | `discover_papers` and `request_ingestion` are rejected in `quick` mode (`mode_not_allowed`) | pass |
| 4 | A crashed worker's lease expires; a second worker reclaims the request and completes it once (PostgreSQL) | pass |
| 5 | The run's generation changes only at the recorded `ingestion_wait` switch; earlier searches use the old generation | pass |
| 6 | At the wait cap the run continues and lists the pending papers | pass |
| 7 | An abstract carrying an injection, obeyed by a scripted "compromised" model, cannot exceed one request or the per-wait paper budget | pass |

## Live evaluation

Two passes over the same 10 families.

- **Natural:** the live model plans and evaluates freely.
- **Forced trigger:** the first plan of each run is scripted to `discover_papers` with the
  question and `request_ingestion` for the family's hidden papers. Everything else is real:
  evaluation and synthesis, the membership policy, the worker, acquisition, Docling
  extraction, child-snapshot validation, waiting and the generation switch.

| Measure | Natural | Forced trigger |
| --- | --- | --- |
| Runs completed / failed | 10 / 0 | 10 / 0 |
| Failed runs with a failure category | — (none failed) | — (none failed) |
| Ingestion-triggering runs | 0 | 9 |
| Within the wait cap | not measurable | 9 of 9 (100%) |
| Generation switches | 0 | 0 |
| Hidden papers ingested | 0 | 0 |
| Tool calls | `search_papers` 19, `search_evidence` 5 | `discover_papers` 15, `request_ingestion` 20, `ingestion_wait` 9 |
| Membership decisions | — | accepted 11, `unknown_paper` 8, `already_indexed` 1 |
| Ingestion outcomes | — | 11 refused: `validation:flagged_table_review_pending` |
| Answer outcomes | 8 insufficient evidence, 2 partially supported | 10 insufficient evidence |
| Median run time | 160 s | 50 s |
| GPU peak memory | 2,622 MiB | 3,912 MiB |
| Spend | $0 | 10 searches ($0.010), 1 content download ($0.010) |

The one family without a hidden paper made no forced request. The 8 `unknown_paper`
decisions were papers the live model proposed itself, none of them hidden papers; the
policy refused them. The one `already_indexed` paper was published to leave-out
generation 2 by the P35-25 acceptance.

**Why no paper was ingested.** Each accepted hidden paper was acquired (one new download;
the others reused stored PDFs) and re-extracted, and each new extraction flagged a results
table for manual review. The
automatic finalization refuses such papers (the Phase 1 rule that an unreviewed flagged
table blocks acceptance), so no child generation was published and no run switched. The
switch path is covered by scripted case 5 and by the P35-25 live acceptance, where a
terminal request for the one hidden paper without flagged tables published leave-out
generation 2.

**Discovery defect found and fixed.** In the forced pass, 12 of 15 `discover_papers` calls
failed (`discovery_error`): the question text was sent to OpenAlex unchanged, and its
`search` parameter rejects wildcard characters such as `?`. `OnlineDiscovery` now removes
`?` and `*` from the search text (unit test added). A two-family forced check after the fix:
both discovery calls succeeded (3 and 0 candidates).

## Limitations

- The live model never chose `discover_papers` or `request_ingestion` on its own, so the wait
  gate rests on the forced-trigger pass. The planner's preference for `search_papers` was
  already recorded as a Phase 4 input after Phase 3.
- Flagged-table review blocks most online ingestion of table-heavy papers; with no manual
  review step online, those papers stay out of the corpus.
- The GPU peak with the API, the worker and Ollama on one 4 GB laptop GPU was 3,912 MiB.
- Ten development families; the leave-out corpus is a variant of the accepted snapshot.
