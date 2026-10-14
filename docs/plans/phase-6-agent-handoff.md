# Phase 6 — Agent handoff

Updated: 2026-10-14. **Status: in progress.** ADR-0032 and ADR-0033 accepted by the owner on
2026-10-13. The [plan](phase-6-portfolio.md) and map issue
[#209](https://github.com/avsngh-git/RAGpipeline/issues/209) define the cards; the
[owner decisions](../reference/phase-6-owner-decisions.md) record the interview.

## How work is picked up

- Each card is a GitHub issue labelled `wayfinder:task`, plus `ready-for-agent` or
  `ready-for-human`, and is a sub-issue of map issue #209. P6-01 to P6-19 are #210 to #228 in
  order. Blockers are native GitHub dependencies
  and a "Blocked by" line.
- Cards run in parallel. Pick any open, unassigned card whose blockers are closed, and claim it
  with `gh issue edit <n> --add-assignee @me`.
- Branch `phase6/p6-NN-short-name`, one pull request per card containing `Closes #<issue>`.
- Agent cards are implemented by Codex Luna agents working alone from the card text (owner
  instruction, 2026-10-06). The planning session reviews each pull request before merge.

## Order

1. P6-01 (planning documents) merges first.
2. In parallel: P6-02 (serving lock, human), P6-03, P6-05, P6-13, P6-14.
3. P6-04 after P6-02; P6-09 after P6-05.
4. P6-06 after P6-04; then P6-07.
5. P6-08 after P6-02, P6-04 and P6-07; P6-16 after P6-09.
6. P6-10, P6-11, P6-12 and P6-15 when their blockers close.
7. P6-17 (gate items 1–2), P6-18 (video), P6-19 (closeout).

## Progress

| Card | State | Commit / PR | Notes |
| --- | --- | --- | --- |
| P6-01 (#210) | merged | c472286 / [PR #229](https://github.com/avsngh-git/RAGpipeline/pull/229) | Hosted CI run [#38407311684](https://github.com/avsngh-git/RAGpipeline/actions/runs/38407311684) passed |
| P6-02 (#211) | merged | PR #230 | Serving lock (CPU PyTorch); image 4.22 GB loads both pinned models on CPU. Hub 1.33.0 pinned by hash in `requirements-serving.txt` (its Conda build conflicts with `mcp=2.3.0`). CPU reranks in fp32; the guard that refused fp16 on CPU was removed, so CPU provenance still names the profile's fp16 (open question) |
| P6-03 (#212) | merged | PR #233 | Merged before review; reviewed on `main`: matches the card. Main CI pushed `sha-6d1d9847734d` |
| P6-04 (#213) | merged | PR #234 | Merged before review; reviewed on `main`: matches the card |
| P6-05 (#214) | merged | PR #235 | Merged before review; reviewed on `main`: matches the card |
| P6-13 (#222) | merged | PR #232 | Links resolve; no private data |
| P6-14 (#223) | merged | PR #231 | Links resolve; spot-checked numbers match the v14 report; caveats stated beside passes |
| P6-06 (#215) | merged | PR #239 | Merged before review; reviewed on `main`: the 35 allowlisted queries and 22 exclusions match the card. Load also disables the two snapshot immutability triggers inside its transaction (needed to load items of a finalized snapshot) |
| P6-09 (#218) | merged | PR #238 | Merged before review; reviewed on `main`: DOM built with `textContent` only, CSP as specified, assets shipped as package data |
| P6-20 (#237) | open | — | Added in review of PR #230: record the reranker's actual device and precision in run provenance |

## Environment facts

- **Machine:** an 11 GiB WSL VM, 12 CPUs, an RTX 3050 Laptop GPU with 4 GiB.
- **Two environments:** CI tests use `environment-linux-64.lock` (no PyTorch). The image is
  built from `environment-serving-linux-64.lock` after P6-02. The host `sci_research_agent`
  environment has torch 2.14.0 (CUDA 13.0), transformers 5.17.0, sentence-transformers 6.1.0,
  huggingface-hub 1.33.0 and docling 2.130.0 outside the lock.
- **Served corpus:** snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` (100 papers, 44,277 chunks),
  collection `research-corpus` (`61cefddc-9fcb-4f75-8280-eae9bce3adf7`) generation 1, Qdrant
  collections `research-passages-gte-bm25-v1` and `research-papers-gte-bm25-v1`, profile
  `frozen-profile-v10-qdrant.toml`.
- **Agents and pushing:** remind each agent to push after its first commit.
- **Live services:** the host API serves on `127.0.0.1:8001`; research runs use the database
  `research_phase1_review`. Agent cards never touch them.
- **Integration tests:** new modules are named `test_phase6_*.py`.
- **Private data:** Phase 6 private data goes under `local-reference/phase6/`.
