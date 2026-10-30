# Research UI

The UI is served by the API at <http://127.0.0.1:8000/> when the Compose small-mode
stack is running. Paste the API key created by `scripts/demo_load.sh` when prompted;
the browser keeps it in the current tab's `sessionStorage`. Disconnect clears it from
that tab. See the [demo quickstart](../../README.md#try-it-about-10-minutes-cpu-only).

The UI has these pages:

- **Search:** search for papers or evidence, with year and evidence-type filters.
  Search results link to paper pages.
- **Paper pages:** show the paper's title, year and document version, its references
  and citing papers, and a search limited to that paper. The API serves paper metadata
  only, so there is no abstract or author list.
- **New run:** submit a question as a quick or deep research run, with an optional
  publication-year range.
- **Runs:** browse the current key's runs, newest first, and open a run page.
- **Run page:** in order, see the run header and status, ingestion state, answer,
  claims and their sources, **How this answer was made**, **What verification
  removed**, **Diagnosis**, and **Budgets and provenance**. While a run is active,
  its status and timeline refresh automatically. The page also offers cancellation.

Search and reading papers or runs require the `read` scope. Starting and cancelling
a run require the `research` scope. A read-only key can still search and inspect
saved runs.

The **Start run** button is disabled according to `GET /v1/me`'s `research_runs`
state:

- `available`: the key has the research scope, the research service is configured,
  and the local model is reachable. Starting a run is enabled.
- `no_research_scope`: the key can search and read runs but lacks `research`. Create
  a key with both `read` and `research` scopes to start or cancel runs.
- `service_unavailable`: the research service is not configured on this server.
- `model_unreachable`: the server cannot reach Ollama, so a run would fail. Search,
  paper pages and saved runs remain available. Start the stack with its `llm` profile
  on a machine with an NVIDIA GPU to run research.

The run timeline can show a model call's prompt, thinking and output only when the
server recorded its payload at trace content level `full` and serves evidence under
`trusted_private_local`. Otherwise the run page reports that the text was “not
recorded” or “withheld”. The released showcase runs include their recorded model-call
text in demo bundle v2.

The showcase runs belong to principal `demo`, so only the demo key created by
`scripts/demo_load.sh` (or an admin key) sees them. Other keys see “This run does not
exist, or it belongs to another key”. An admin key opens them by link; **Runs** lists
only the current key's own runs.

Set `RESEARCH_PLATFORM_LANGFUSE_UI_URL` to the Langfuse project's traces page when
the observability profile runs. The run page appends the run's trace ID to that URL
for its **Open trace in Langfuse** link.

Cancelling an active run marks it failed with category `cancelled_by_principal` and
keeps its partial run record, including recorded tool calls, model calls and drafted
claims. Cancelling a run that has already finished is refused (`409 run_not_active`)
and the run is unchanged.

See [ADR-0034](../adr/0034-phase6-product-ui.md) for the accepted UI decision.
