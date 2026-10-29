# Phase 6 gate report

**Status:** gate items 1 and 2 passed on 2026-10-14 for `v0.6.0`, and again for the product UI
on `v0.6.1` and `v0.6.2` (2026-10-24 to 2026-10-29, [below](#rerun-on-the-product-ui-p6-32)).
Item 3 passed on 2026-10-29: the owner accepted the video ([below](#gate-item-3-the-video)). The gate is defined in
[ADR-0033](../adr/0033-phase6-delivery-without-hosting.md) decision 8; ADR-0034 decision 7 asks
for the rerun. Cards: [P6-17 (#226)](https://github.com/avsngh-git/RAGpipeline/issues/226) and
[P6-32 (#268)](https://github.com/avsngh-git/RAGpipeline/issues/268).

## Release under test

- **Release:** [`v0.6.0`](https://github.com/avsngh-git/RAGpipeline/releases/tag/v0.6.0) on
  commit `977e7aa`. The Release workflow promoted the image CI had already built and scanned,
  `sha-977e7aab25a9`, to `v0.6.0` and `latest` without rebuilding (digest
  `sha256:6e9b36059b2ba1a2964cb004730445fe652eb1dc385e9cee2ca92351c211af09`).
- **Image registry:** `ghcr.io/avsngh-git/ragpipeline` is public; an anonymous pull of the
  manifest returns 200.
- **Demo data:** release [`demo-data-v1`](https://github.com/avsngh-git/RAGpipeline/releases/tag/demo-data-v1)
  (353,638,400 bytes). It holds the accepted 100-paper CC BY snapshot after a per-document display
  review ([ADR-0032](../adr/0032-phase6-public-cc-by-demo-collection.md)), its index generation and
  eight showcase runs (2 answered, 5 partially supported, 1 insufficient evidence). P6-11
  (#220) records how it was made and checked.

## Gate item 1: the README quickstart on a fresh runner

The Demo smoke workflow ran automatically after the Release workflow:
[run 38576130251](https://github.com/avsngh-git/RAGpipeline/actions/runs/38576130251), 7 minutes
from start to finish on `ubuntu-latest`. It ran `scripts/demo_load.sh` and `docker compose up -d`
exactly as the README says, then `scripts/demo_smoke.py`:

| Check | Result |
| --- | --- |
| `ready` | pass |
| `serving` (snapshot and profile match the bundle) | pass |
| `paper_search` | pass, 5 hits |
| `evidence_search` | pass, 5 hits with text |
| `runs` (claims carry quotes; cited papers present) | pass, 8 runs, 11 claims |
| `mcp_tools` | pass, 8 of 8 tools |

**Passed.** Two local fresh-clone runs agree: `demo_load.sh` took 634 s and 568 s on the laptop
CPU, and the smoke checks took under 3 s.

## Gate item 2: cold review

A fresh agent got only the public repository and the instruction to evaluate it for a hiring
decision. It had no project memory, no planning conversation and no private files. It followed
the README and docs, ran the small mode and the tests, and checked five README claims against
their sources.

**Result:** it described the production design correctly in its own words, and judged that it
could discuss the system in an interview "Yes". Four claims verified; one was verified with a
wording correction (fixed). The small mode passed 6 of 6 checks.

| Finding | Resolution |
| --- | --- |
| A second checkout in a directory of the same name shares the Compose project, so the quickstart took over the owner's running stack (no data lost; the bundle load refused because the collections existed) | README documents `COMPOSE_PROJECT_NAME` and the port variables ([PR #251](https://github.com/avsngh-git/RAGpipeline/pull/251)). A fixed `name:` in the Compose file was set aside: it would make every clone collide |
| `demo_load.sh` printed links on port 8000 regardless of `API_PORT` | Fixed in #251 |
| `demo_smoke.py` pointed at a README section that does not exist | Fixed in #251 |
| README said the profile uses BM25S; serving uses Qdrant sparse vectors | Fixed in #251 |
| README attributed local Phase 5 test counts to the CI gate run | Fixed in #251 |
| README development setup omitted `requirements-langgraph.txt` (78 test collection errors) | Fixed in [PR #252](https://github.com/avsngh-git/RAGpipeline/pull/252), with the exact lock CI uses |
| A Phase 3 test fails at import in a checkout under the system temporary directory | Documented in #252 (the guard protects private data) |
| The MCP URL in the README ignored `API_PORT`; disk and memory figures were unverified | Fixed in #252 with measured components |
| 422 responses do not name the invalid field | Backlog [#253](https://github.com/avsngh-git/RAGpipeline/issues/253) |
| One embedding test failed once and passed twice on rerun | Backlog [#254](https://github.com/avsngh-git/RAGpipeline/issues/254) |

**Passed:** every finding is fixed or recorded.

## Bugs found while running the gate

The unit tests of the demo cards had not exercised a real end-to-end path. Running it found three
bugs, all fixed before the release:

- `research-demo export` and `load` crashed on connect ([PR #248](https://github.com/avsngh-git/RAGpipeline/pull/248));
- `demo_load.sh` exited 1 while printing the run links after a successful load ([PR #249](https://github.com/avsngh-git/RAGpipeline/pull/249));
- capturing the demo key failed in an interactive terminal ([PR #244](https://github.com/avsngh-git/RAGpipeline/pull/244)).

## Incidents

- **2026-10-14, 13:28:** the WSL VM crashed while the P6-12 agent was working in the main
  checkout without having pushed. The crash left `README.md` empty and an empty branch ref. The
  README was restored from `main` and the card restarted
  ([#221](https://github.com/avsngh-git/RAGpipeline/issues/221)).
- **2026-10-14:** the first cold-review run joined the owner's Compose project (first finding
  above). Containers were recreated on the owner's volumes; migrations were already current
  (028); the bundle load refused. The owner's stack was restored on its default ports, and runs,
  permission records and Qdrant point counts were verified intact.

## Rerun on the product UI (P6-32)

[ADR-0034](../adr/0034-phase6-product-ui.md) decision 7 reruns gate items 1 and 2 after the
product UI (P6-21 to P6-31).

### Release `v0.6.1`

- **Release:** [`v0.6.1`](https://github.com/avsngh-git/RAGpipeline/releases/tag/v0.6.1) on
  commit `6c42844`, published 2026-10-24. The Release workflow promoted `sha-6c428442ad15`
  without rebuilding (digest
  `sha256:148d790575d5980c6fecda75c1fe2fcc7a2f3c5fef591d63f9a98951ce92e689`).
- **Demo data:** release [`demo-data-v2`](https://github.com/avsngh-git/RAGpipeline/releases/tag/demo-data-v2)
  (353,781,760 bytes): the v1 collection and showcase runs plus their recorded model-call text
  (P6-30).
- **Gate item 1:** Demo smoke
  [run 40089248595](https://github.com/avsngh-git/RAGpipeline/actions/runs/40089248595) passed
  11 of 11 checks on `ubuntu-latest` in 4 minutes. The five added checks cover the UI modules,
  `GET /v1/me`, the run list, the run records of all eight showcase runs and model-call text.

### Cold review of `v0.6.1`

A fresh agent got only the public repository, its releases and issues, and ran everything in its
own Compose project and ports. The quickstart worked first time (695 s), `demo_smoke.py` passed
11 of 11, the full test suite passed with database services (1,655 tests) and the 12 browser
journeys passed. Five README claims matched their sources. It described the production design
correctly and judged that it could discuss the system in an interview.

| Finding | Resolution |
| --- | --- |
| `fetch-models` downloaded every model format; the model cache was 6.7 GB and the README disk figures were about half the measured 15 GB | Download limited to the files the server loads (863 MB) in [P6-34, PR #285](https://github.com/avsngh-git/RAGpipeline/pull/285); README figures re-measured in [P6-35, PR #287](https://github.com/avsngh-git/RAGpipeline/pull/287) |
| `demo_smoke.py` was undocumented and ignored `API_PORT`, so it tested another stack on port 8000 | Reads `API_PORT` (#285); README "Check the demo" step (#287) |
| The quickstart pulled `:latest`, which on the reviewer's machine was still the `v0.6.0` image; deployment examples used `v0.6.0` | Quickstart clones a release tag and sets `RESEARCH_PLATFORM_IMAGE` to it; examples use `vX.Y.Z` (#287) |
| Failed verification checks read as passed (“failed quote verification: quote found”); diagnosis findings read wrongly | Plain reasons and labels on the run page (#285) |
| With the read-only demo key, **New run** never said a run needs a GPU | Notice names the NVIDIA GPU and the `llm` profile (#285) |
| The key page said the key was “printed”; unknown paper IDs rendered as real papers; three smaller UI issues | Fixed in #285 |
| The second quickstart command did nothing; cleanup needs `sudo` (Docker creates `data/` as root) | Command removed; "Remove the demo" note (#287) |
| The results table omitted caveats: Phase 2 thresholds were lowered after v13 failed; Phase 4 reproduces only at each run's recorded commit | Caveats added (#287) |
| Development setup: the Conda environment name can collide, the Playwright browser install and the integration test services were undocumented | `--name` note, Chromium install and a services recipe (#287) |
| Showcase runs are visible only to the demo key | Documented in the UI guide (#287) |
| 422 responses do not name the invalid field | Already backlog [#253](https://github.com/avsngh-git/RAGpipeline/issues/253) |
| A claim passed with a quote ending in “...” and a stronger verb than its quote | Answer quality is out of scope (owner decision Q1); noted on backlog [#115](https://github.com/avsngh-git/RAGpipeline/issues/115) |
| The README video link is a `TODO(owner)` | Replaced by P6-18 |

**Passed:** every finding is fixed or recorded.

### Release `v0.6.2`

- **Release:** [`v0.6.2`](https://github.com/avsngh-git/RAGpipeline/releases/tag/v0.6.2) on
  commit `ad013d0`, published 2026-10-29, with the P6-34 and P6-35 fixes and the dependency
  advisory fixes ([PR #282](https://github.com/avsngh-git/RAGpipeline/pull/282),
  [PR #286](https://github.com/avsngh-git/RAGpipeline/pull/286)). The Release workflow promoted
  `sha-ad013d0c547c` without rebuilding (digest
  `sha256:765bfb617c706a7eb0ddab95b16a1866aded5d7ec757a0cce4a793082d9b708b`).
- **Gate item 1:** Demo smoke
  [run 40882980828](https://github.com/avsngh-git/RAGpipeline/actions/runs/40882980828) passed
  11 of 11 checks on `ubuntu-latest` in 3 minutes with bundle `demo-data-v2`.
- **Local fresh clone:** the README quickstart on `main` at `5301dd5` (P6-35) took 272 s with the
  PostgreSQL and Qdrant images already cached and passed 11 of 11. Measured disk use was 8.8 GB
  (models 0.9 GB, down from 6.7 GB).
- The workflow still runs `docker compose up -d --wait` after `demo_load.sh`, under a step label
  that names the removed README step. The command is a no-op on a running stack.

## Gate item 3: the video

The owner accepted the video on 2026-10-29 ([P6-18, #227](https://github.com/avsngh-git/RAGpipeline/issues/227));
it is embedded in the README. It runs 1 min 25 s: a live deep research run on the reference question
(run `18800d70`, `main` at `ff56c10`, partially supported, 3 verified claims, 4 min 43 s on the RTX 3050),
with the question and answer at normal speed and the working time shown as a clock with the run's
real step timings and six project highlights.

- It departs from the [video script](../demo/video-script.md): no showcase run, MCP or CI segments, and
  no narration.
- The answer cites three OpenAlex abstracts of papers outside the demo collection. The owner accepted
  showing them as CC0 metadata ([owner decisions](phase-6-owner-decisions.md), entry 4).

**Passed.**

## Remaining

- Closeout and `v1.0.0` (P6-19, #228).
