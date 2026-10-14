# Phase 6 gate report

**Status:** gate items 1 and 2 passed on 2026-10-14; item 3 (the owner accepts the video) is
P6-18. The gate is defined in [ADR-0033](../adr/0033-phase6-delivery-without-hosting.md)
decision 8. Card: [P6-17 (#226)](https://github.com/avsngh-git/RAGpipeline/issues/226).

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

## Remaining

- Gate item 3: the owner records and accepts the video (P6-18, #227).
- Closeout and `v1.0.0` (P6-19, #228).
