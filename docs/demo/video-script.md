# Recruiter demo video script

> **Superseded on 2026-10-29.** The owner accepted a shorter video without narration, embedded in the [README](../../README.md#video); see [owner decisions](../reference/phase-6-owner-decisions.md) entry 4 and the [gate report](../reference/phase-6-gate-report.md#gate-item-3-the-video). This script records the original plan.

This script is for a 3–5 minute recording on the GPU host, as set in [the Phase 6 owner decision](../reference/phase-6-owner-decisions.md) and [ADR-0033](../adr/0033-phase6-delivery-without-hosting.md). Keep the recording focused on the research path and the engineering behind it.

## Setup checklist

- Start PostgreSQL and Qdrant with `docker compose up -d postgres qdrant`. Start Ollama with `docker compose --profile llm up -d ollama`, and start the host API as described in the [Phase 3 generator guide](../operations/phase-3-generator.md). The services are defined in [`docker-compose.yml`](../../docker-compose.yml).
- Confirm the reviewed showcase runs are loaded. Choose a run whose display permission is confirmed, with claims, verified quotes, and papers. Keep its run ID in a private note for recording; do not add it to this file. The bundle is designed to include approved showcase runs and per-paper attribution ([ADR-0032](../adr/0032-phase6-public-cc-by-demo-collection.md), [ADR-0033](../adr/0033-phase6-delivery-without-hosting.md)).
- TODO(owner): select a loaded showcase run that has a public-display-approved table hit. Confirm the selected evidence is allowed for public display under [ADR-0032](../adr/0032-phase6-public-cc-by-demo-collection.md); if none is available, omit its text and record that limitation.
- For the live run, use the public reference question in [source of truth §2.5](../agents/scientific-research-platform-source-of-truth.md). Before recording its result, confirm every displayed source is covered by a public display record and the bundle attribution. If any source cannot be confirmed, show the run status only and cut the result.
- Keep the UI key in a local password manager or environment. Enter it only in the UI; it is held in tab `sessionStorage` ([UI implementation](../../src/research_platform/api/static/app.js)).
- Use a key with `read` and `research` scopes in the browser for the live run.
- Set `RESEARCH_PLATFORM_LANGFUSE_UI_URL` if the Langfuse profile runs.
- Set a readable terminal font and browser zoom. Turn off notifications. Close windows that are not part of the demo.
- Open the UI at <http://127.0.0.1:8001/> ([GPU-host run guide](../operations/phase-3-generator.md), [UI route](../../src/research_platform/api/app.py)). Keep a terminal ready for `research-runs explain RUN_ID`, the Langfuse trace page at <http://127.0.0.1:3000> if the optional observability profile is running ([observability guide](../operations/observability.md)), and Claude Code connected to the `scientific-research` MCP server ([MCP guide](../operations/mcp.md)).
- Keep a local `RESEARCH_MCP_KEY` available to Claude Code without displaying the value. Use a key with `read` and `research` scopes for the live run ([MCP guide](../operations/mcp.md)).
- TODO(owner): after P6-17, replace the image reference in the final segment with the released version tag and confirm the small-mode quickstart works from a clean checkout ([Phase 6 gate](../adr/0033-phase6-delivery-without-hosting.md)).

## Script

The seven segments total 4 minutes 30 seconds. Cut or speed up the model wait; keep the evidence and diagnosis visible long enough to read.

| Segment | Time | What is on screen | What to say |
| --- | --- | --- | --- |
| The problem and the claim | 0:00–0:20 | Start on the project name, then show the UI. | “I built a research system that searches scientific papers and ties each answer claim to evidence. I’ll show the search, the checks behind a claim, and the same capability through MCP.” ([project overview](../architecture/overview.md), [source of truth](../agents/scientific-research-platform-source-of-truth.md)) |
| A showcase run | 0:20–1:10 | Open the prepared run with `#run=<run_id>`. Show its status, claims, verified quote, paper title, and year. | “I’m showing a reviewed showcase run. I can read each claim beside the verified quote and the paper it cites.” ([UI implementation](../../src/research_platform/api/static/app.js), [ADR-0025](../adr/0025-verified-quote-synthesis-with-thinking.md)) |
| Search | 1:10–1:40 | Search for papers, then evidence. Open the prechecked table hit and show its heading, page, and table rows. | “I can search for papers or evidence. Here I can inspect the source location and table context behind this result.” ([UI implementation](../../src/research_platform/api/static/app.js), [search pipeline](../architecture/overview.md)) |
| A live deep research run | 1:40–2:40 | Start the public reference question from **New run** in the browser with **Deep research**. Show the run page while “How this answer was made” fills in; open “Prompt, thinking and output” on a planning call. Cut or speed up the wait. Show the result only after the display check already required above. | “Now I’m starting a live run on the GPU host with the project’s public reference question. I’ll show its result only after checking that every source is cleared for display.” ([reference question](../agents/scientific-research-platform-source-of-truth.md), [UI guide](../operations/ui.md), [ADR-0032](../adr/0032-phase6-public-cc-by-demo-collection.md)) |
| Why I can inspect it | 2:40–3:20 | On the same run page, scroll through “What verification removed”, “Diagnosis” and “Budgets and provenance”. Follow “Open trace in Langfuse” if the observability profile runs. Optionally show `research-runs explain RUN_ID` in the terminal for five seconds. | “I can inspect which stage ran, what verification removed, and the limits recorded for this run. The trace adds timing, while the run record keeps its configuration and budget.” ([run record](../operations/ui.md), [run diagnosis](../../src/research_platform/runs/cli.py), [trace guide](../operations/observability.md)) |
| The same capability over MCP | 3:20–4:00 | In Claude Code, ask it to search for “reranking” using `search_papers`; show the tool call and returned paper results. Keep the key and any private configuration out of view. | “I asked Claude Code to search through the same research services over MCP. I can see the tool call and its paper results without showing the key.” ([MCP operations](../operations/mcp.md), [architecture](../architecture/overview.md)) |
| Engineering and next steps | 4:00–4:30 | Show the CI workflow, the published image reference, and the documented small-mode quickstart; finish on the architecture and benchmark docs. | “I can run the local CPU small mode and inspect the published image and automated checks. I can read the architecture, benchmarks, and failure analysis to understand the choices and limits.” ([CI workflow](../../.github/workflows/ci.yml), [release decision](../adr/0033-phase6-delivery-without-hosting.md), [architecture](../architecture/overview.md), [benchmarks](../reference/benchmarks.md), [failure analysis](../reference/failure-analysis.md)) |

## Recording notes

- Use any screen recorder; OBS works on Windows. Record at 1080p.
- Cut or speed up the live run wait. Do not cut the evidence review or the diagnosis.
- Add captions and check that commands, claims, and table headings remain readable.
- Upload the finished video as unlisted on YouTube.
- Export a 10–20 second GIF from the showcase segment for the README.

## What not to show

- API keys, bearer headers, password-manager entries, or terminal history that contains secrets.
- `local-reference/` paths or files, local usernames, private development questions, or unreviewed run content.
- A passage, claim quote, table, or answer that has not passed the public-display check.
- Private database URLs, model-cache paths, environment variables, or unrelated terminal output.
