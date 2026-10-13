# Phase 6 — Agent handoff

Updated: 2026-10-13. **Status: planned.** ADR-0032 and ADR-0033 accepted by the owner on
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
