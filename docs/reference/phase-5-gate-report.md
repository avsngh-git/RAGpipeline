# Phase 5 gate report

**Status:** gate items 1–3 pass in CI; item 4 ran on 2026-10-12 and awaits the owner's
review. Prepared 2026-10-12.

The phase gate (source of truth section 21): *an external MCP client and the internal
LangGraph agent use the same core research capability without duplicated business logic.*
ADR-0030 decision 11 makes it four checks. The live session's transcripts stay private under
`local-reference/phase5/`. No question, answer, claim, quote or passage text is reproduced
here.

## Gate items

1. **Parity — passed in CI.** `tests/test_phase5_gate_parity.py` (P5-13, PR #203): on the
   same fake services, each MCP tool returns the same identifiers, ranks and statuses as the
   HTTP route and, where the agent has the tool, as `ResearchTools`; a spy shows HTTP routes
   and MCP tools reach the same `ResearchCapabilities` methods.
2. **Import boundary — passed in CI.** `tests/test_phase5_gate_import_boundary.py` (P5-13):
   the MCP adapter and the capability service import no database, vector-store, ranking,
   ingestion or agent module (name-limited exceptions for error and contract types); routes
   and MCP tools call no service directly.
3. **MCP security suite — passed in CI.** `tests/security/test_mcp_attacks.py` (P5-14,
   PR #204): keys, scopes, rate limits, the active-run cap, run ownership, body limit, host and
   origin checks, the text exposure policy, inert injected arguments, cursor tampering and
   legacy clients.

   Items 1–3 passed together on `main` at `7c7193a` in
   [CI run 38292707408](https://github.com/avsngh-git/RAGpipeline/actions/runs/38292707408)
   (locally: 1407 passed, 114 skipped).

   **Mutation checks (2026-10-12, planning session).** Each gate test was confirmed to fail
   when its control is broken on purpose:

   | Deliberate break | Failing tests |
   | --- | --- |
   | `import asyncpg` in an MCP module | import boundary |
   | An MCP search tool calls the search service directly | parity and import boundary |
   | The text policy always lets text out | security suite |
   | The per-tool scope check is skipped | security suite |
   | A run may ingest without the `ingest` scope | security suite |

4. **Live external-client session — ran 2026-10-12; owner review pending.** The API ran from
   `main` (`7c7193a`) on `127.0.0.1:8001` against `research_phase1_review` (migration 028
   applied; 218 existing runs keep `ingestion_permitted = true`), text policy
   `public_display_only`. Key `ab9a088c` (principal `p5-16-mcp`, scopes `read` and `research`,
   no `ingest`). Client: MCP Inspector CLI 2.8.0 via `scripts/mcp_inspector_check.sh`, one
   development question (`q03`). Transcript: `local-reference/phase5/inspector/20261012T185132Z/`.

   | Check | Result |
   | --- | --- |
   | Server surface | 8 tools and 2 resource templates; read-only hints on all but `start_research_run`; protocol `2026-07-28` |
   | `search_papers` | `ranked_candidates`, 10 of 100 eligible papers, 15 supporting passages, all with text withheld |
   | `get_paper` | metadata for an in-snapshot paper |
   | `start_research_run` (`quick`) | run `0de45d17-f140-4c9f-a3ae-d2c73069df2e` queued, `poll_after_seconds` 30 |
   | `get_research_run`, polled | `completed` after about 6 minutes, outcome `answered`, 2 claims citing 1 paper, quotes withheld, no poll hint |
   | Same run over HTTP, same key | every field equal to the MCP view except claim quotes, which HTTP returns and MCP withholds; claim and evidence IDs identical |
   | Run record | principal `p5-16-mcp`, `ingestion_permitted = false`, mode `quick` |
   | HTTP read without a key | 401 |
   | `research-runs explain` | completed, quick, answered, stage `none` |

   The run went through the same `ResearchCapabilities.start_run` and LangGraph runner as an
   HTTP run, which is what the gate asks.

## Findings during Phase 5 review

- **Run tools missing in the running API (fixed, PR #199).** P5-12 registered the run tools
  only when research services existed at server creation; the API builds them later, so the
  live server would have lacked them. Caused by P5-09's skeleton test asserting an empty tool
  list.
- **Import cycle (fixed, PR #201).** Importing an MCP module before `create_app` failed through
  `research_platform/api/__init__`.
- **Concurrent searches (fixed, PR #207, closes #205).** Found in the Claude Code demo below:
  the query embedder rejected a query while another was in flight. It now waits up to the
  query timeout. Live check, 4 parallel MCP searches × 3 rounds: 3 errors per round before,
  0 after.
- **Workflow.** Several agent cards were committed but not pushed, and three cards were merged
  before review; each was reviewed on `main` afterwards.

## Claude Code demo (reported, not gated)

Run on 2026-10-12 under owner decision 2 (passage text sent to the owner's own client),
with the API restarted at `trusted_private_client` for the demo and returned to
`public_display_only` afterwards.

- **Setup:** Claude Code 2.1.296, headless (`-p`), with only this MCP server loaded
  (`--strict-mcp-config`), only MCP tools allowed, an empty working directory, the same
  `read`+`research` key, and one development question (`q01`) with a neutral instruction to
  answer from the corpus with cited paper IDs and quotes. Session log:
  `local-reference/phase5/p5-16/claude-demo/session.jsonl`.
- **Tool choice:** the model chose `search_papers` once and `search_evidence` twice, the
  second time scoped to specific papers with `paper_ids`. It did not start a research run.
  5 turns, 20 seconds.
- **Answer:** cited 4 corpus paper IDs and quoted 6 passages. Answer quality was not reviewed
  (outside this phase).
- **Finding:** the model sent `search_papers` and `search_evidence` in one turn; the second ran
  concurrently and failed with `dependency_unavailable`, because the query embedder rejects a
  query while another is in flight (`EmbeddingInferenceBusy`). The agent never hits this
  because it calls tools one at a time. Filed as
  [#205](https://github.com/avsngh-git/RAGpipeline/issues/205) and fixed in PR #207.
- Two earlier launch attempts sent the model a prompt with an empty question (a bug in the
  demo's launcher script); the model asked for the question and made no tool calls.
