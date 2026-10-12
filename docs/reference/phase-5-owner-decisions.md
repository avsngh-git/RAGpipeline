# Phase 5 owner decisions

**Status:** record of the owner's judgement calls during Phase 5, kept for later analysis.
Each entry gives the date, what was decided, the evidence it rested on, the alternatives
set aside, and what to re-examine later. Decisions delegated to the assistant are listed
separately at the end.

## Owner decisions

### 1. Planning interview (2026-10-12)

The owner answered 13 questions, chose option (a) on scope (Q1) and accepted the assistant's
recommendation on every other question. ADR-0030 and ADR-0031 record the resulting design;
map issue [#169](https://github.com/avsngh-git/RAGpipeline/issues/169) lists the cards.

Evidence available at the time:
- **Spec:** section 21 makes Phase 5 the MCP phase; the Phase 4 closeout lists answer
  quality as the main open gap, and backlog
  [#115](https://github.com/avsngh-git/RAGpipeline/issues/115) carries the
  2026-10-11 answer-quality findings.
- **MCP:** specification revision 2026-07-28 removes protocol sessions and the
  `initialize` handshake and deprecates Roots, Sampling and Logging. The official Python
  SDK `mcp` 2.3.0 (2026-10-02, on conda-forge) implements it and still serves 2025-era
  clients.
- **Code:** `ResearchTools` already calls framework-independent service protocols; the API
  routes and the agent share them.

| # | Topic | Decision | Alternatives set aside |
| --- | --- | --- | --- |
| Q1 | Scope | MCP only, as section 21 defines Phase 5. Answer-quality work stays in backlog #115 | MCP plus a parallel answer-quality track; answer quality first, MCP moved to Phase 6 |
| Q2 | Tools | Eight tools: the six retrieval and graph tools plus `start_research_run` and `get_research_run` (run ID polling). `discover_papers` and `request_ingestion` are not exposed | Six retrieval tools only; also exposing discovery and ingestion |
| Q3 | Process | Mount the MCP Streamable HTTP app at `/mcp` inside the FastAPI process, sharing its services; a second process would load the retrieval models (about 1.9 GiB) again on the 4 GiB GPU | Separate `research-mcp` process |
| Q4 | Transports | Streamable HTTP only; stdio set aside for the same GPU reason. Client configuration is documented | A CPU-retrieval stdio entry point; a stdio-to-HTTP bridge |
| Q5 | Authentication | Reuse the Phase 4 API keys through a custom `TokenVerifier`: same scopes, rate-limit buckets and run ownership. OAuth revisited in Phase 6 only if the demo needs it | OAuth 2.1 with an authorization server |
| Q6 | Passage text | MCP results carry passage text only for papers whose permission evidence allows public display; others return identifiers, locations and metadata. Needs an ADR | The HTTP API's private-inspection rule; never return text |
| Q7 | Gate | (1) CI parity: MCP tool results equal `ResearchTools` and HTTP route results on the same fakes; (2) CI import boundary for `research_platform.mcp`; (3) CI auth, scope, rate-limit and data-boundary tests; (4) a live external-client session reviewed by the owner | — |
| Q8 | Run modes | `start_research_run` allows `quick` and `deep_research`. A deep run may trigger ingestion only if the starting key also has the `ingest` scope; the check sits in the shared run-start service, so the HTTP API changes the same way. Evidence: today a `research`-only key's deep run can request ingestion | Same rules as HTTP today; `quick` only |
| Q9 | Resources | Two resource templates, `paper://{paper_id}` and `research-run://{run_id}`, over the same readers as the tools. No prompts | Tools only; adding `literature_review` and `compare_methods` prompts |
| Q10 | Waiting for runs | The client polls `get_research_run(run_id)`; results suggest a polling interval | The `io.modelcontextprotocol/tasks` extension; a blocking call |
| Q11 | Text policy in practice | Evidence: `passage_display_permitted` is false on all 102 artifacts and 103 rights reviews, so the Q6 rule alone returns no text. Strict by default; the server-only setting `RESEARCH_PLATFORM_MCP_TEXT_POLICY=trusted_private_client`, set only on the owner's laptop, returns text as the private HTTP API does. The owner records that their own client receiving text, including its forwarding to the client's model provider, is private non-commercial use | Always strict; short quotes only |
| Q12 | Live check client | MCP Inspector CLI for gate item 4 (no model, nothing leaves the laptop); a Claude Code session as a reported, ungated demo under the Q11 setting | Inspector only; Claude Code only |
| Q13 | Phase 4 leftovers | One `ready-for-human` housekeeping card first: resolve or renew the seven Trivy exceptions before they expire on 2026-11-06, mark experiment `083f3b19` interrupted, recreate the Ollama container for the PR #157 cache limit. Unmerged answer-quality candidates stay with #115 | Leave them to #115 or Phase 6 |

### 2. Passage text for the owner's Claude Code demo (2026-10-12)

**Decision:** for the P5-16 Claude Code demo only, the API on the owner's laptop runs with
`RESEARCH_PLATFORM_MCP_TEXT_POLICY=trusted_private_client`, so the owner's own key and client
receive passage text and claim quotes. The owner judges this, including Claude Code sending
tool results to Anthropic's API, to be private non-commercial use under the corpus's CC BY-NC-ND
and personal-use terms (ADR-0031 decision 3). The policy returns to `public_display_only` after
the demo.

**Evidence:** `passage_display_permitted` is false for every paper, so without this setting the
model sees titles, IDs, ranks, pages, sections and claim text but no passages. The gate itself
(item 4, MCP Inspector) ran under the default policy.

**Alternatives set aside:** a metadata-only demo; skipping the demo.

**Re-examine:** before any deployment or sharing of the platform, and if a model provider's
data terms change.

## Decisions delegated to the assistant

Proposed in the interview; the owner did not object (2026-10-12):

- `snapshot_id` is optional on MCP tools and defaults to the served snapshot; another ID
  gets `incompatible_snapshot`.
- `mcp==2.3.0` pinned through the Conda lock in one dependency card.
- Typed structured tool output; `readOnlyHint` on the seven read tools.
- Each tool uses an existing rate-limit class: searches `SEARCH`, paper and graph reads
  `PAPER_READ`, run start `RESEARCH_CREATE`, run read `RUN_READ`.
- Service errors become MCP tool errors carrying our error code; invalid arguments become
  JSON-RPC invalid-params errors.
- One span and metric per tool call at the existing trace content levels; a client
  `traceparent` is recorded, not used as the parent.
- Q8 mechanism: runs record `ingestion_permitted` at creation (migration 028); when false,
  the ingestion policy refuses with `ingest_scope_required`. Prompts and tool lists do not
  change.
- Two ADRs: 0030 (MCP adapter) and 0031 (passage exposure to external clients).
- Tool names match the internal tools; `get_research_run` returns the HTTP
  `ResearchRunView`, filtered by the text policy.
- Workflow as in Phase 4: map issue, `P5-NN` cards, `phase5/p5-NN-short-name` branches,
  one pull request per card, review before merge.

Made by the planning session while writing ADR-0030 and the cards (2026-10-12), after the
SDK spike; the owner confirmed the plan and asked for the cards:

- **Authentication mechanism (refines Q5).** An ASGI wrapper (`McpAuthGate`) calls the same
  key check as the HTTP dependency, in place of the SDK `TokenVerifier`. The SDK path needs an
  OAuth issuer URL and publishes resource metadata naming an authorization server that does
  not exist. The decision itself, reusing Phase 4 keys, scopes and limits, is unchanged.
- **Invalid arguments.** They come back as MCP tool errors, as the SDK does, not as JSON-RPC
  invalid-params errors (refines the interview default).
- **Client trace context.** Not used as a span parent and not recorded (simplifies the
  interview default "recorded, not trusted").
- **Stateless JSON transport.** `stateless_http=True` and `json_response=True`, so no session
  state exists for 2025-era clients either.
- **Shared capability service.** The HTTP routes' use-case logic moves into
  `ResearchCapabilities`, so HTTP and MCP share it; without this, the MCP adapter would
  duplicate business logic and fail the gate.
- **Strict text policy withholds all text.** No record permits public display and the access
  policy's `can_display_public` is always false, so no per-paper display reader is built now
  (ADR-0031).
- **`find_related_papers`** uses shared references and co-citations only, not embedding
  similarity.
- **MCP Inspector** pinned at 2.8.0 (released 2026-09-23).

## P5-02 housekeeping execution (2026-10-12; implementation complete)

- **Experiment `083f3b19-03b8-4970-887b-8670ea5cc053`:** it was still `running`, had zero
  items, and had no completion time. The experiment schema permits only `running`,
  `completed` and `failed`; it has no `interrupted` state, and the CLI has no status-edit
  command. A guarded SQL update for this ID while its state was still `running` set status
  to `failed`, set `completed_at`, and appended an interruption note while preserving the
  existing notes and other fields. The resulting row was returned as `failed`.
- **Ollama cache limit:** recreated the service with
  `docker compose --profile llm up -d --force-recreate ollama` to apply the merged PR #157
  setting. The recreated container reports `LLAMA_ARG_CACHE_RAM=1024`.
- **Trivy exceptions:** removed all seven entries from `.trivyignore` after patching the
  image layers. The Ubuntu base now upgrades `libssl3t64` and `openssl` to the newest
  Ubuntu security release (`3.0.13-0ubuntu3.16` on 2026-10-12). The owner chose an unpinned
  upgrade over an exact version pin, because Ubuntu's apt index keeps only the newest version
  and an exact pin would fail every image build after the next OpenSSL update; the base image
  digest stays pinned and the CI Trivy scan checks the result. The Miniforge base now refreshes Conda to `26.9.2`, which updates
  `py-rattler` to `0.26.0` and `urllib3` to `2.8.0`; the runtime lock already pins fixed
  `setuptools`, `msgpack-python` and `urllib3` versions. Trivy identified the remaining
  setuptools/msgpack vendor advisories in pip's embedded vendor BOM, not the installed
  package metadata. Pip is only needed while building the image: base pip is removed after
  the base refresh, and app-environment pip is removed after package installation. The
  rebuilt app imports successfully without pip. Trivy 0.70.0, using the CI HIGH/CRITICAL and
  `ignore-unfixed` policy with exceptions disabled, reports zero findings.
- **Card evidence:** the image was built from the P5-03 lock in its isolated worktree with
  the P5-02 Dockerfile. The Trivy scan was a local CI-equivalent check; hosted CI remains
  pending publication of the cards' PRs.
