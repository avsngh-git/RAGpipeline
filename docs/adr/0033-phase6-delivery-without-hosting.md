---
status: accepted
date: 2026-10-13
---

# Phase 6: released images, a reviewer small mode and no hosted environment

Accepted by the project owner on 2026-10-13 in the Phase 6 planning interview
([owner decisions](../reference/phase-6-owner-decisions.md)). It changes LOCKED goal 16 of
section 3.1, section 18.2 and the section 22 deployment item, with the owner's approval.

## Context

- Section 21 asks Phase 6 for versioned images, a release/deployment workflow, one real deployed
  environment, a thin UI or API demo, documentation and a recorded demo. Its gate: a reviewer can
  clone, run a small mode, inspect tests and results, and understand the production design without
  private knowledge.
- The owner will not accept any hosting bill. A 2026-10-13 check of free tiers found none that is
  $0, needs no card and has the RAM to serve the retrieval models: Hugging Face Docker Spaces now
  need a paid plan and block outbound database ports; Oracle Always Free needs a card and an arm64
  image; Cloud Run has no hard spend cap; Render, Koyeb, Fly and Railway are too small or not free.
  The generator needs the laptop GPU in any case (median synthesis 215 s on the RTX 3050).
- The locked Conda environment (`environment-linux-64.lock`) used by CI and the image has no
  PyTorch, transformers or sentence-transformers. The host environment that produced every live
  result has torch 2.14.0 (CUDA 13.0), transformers 5.17.0, sentence-transformers 6.1.0,
  huggingface-hub 1.33.0, tokenizers 0.23.2 and safetensors 0.8.0, installed outside the lock. The
  image therefore cannot serve search today.
- CI builds and scans the image but never pushes it; there are no tags or releases.
- `research_platform.persistence.migrations.MIGRATIONS_DIR` resolves from the source tree, and the
  image does not contain `migrations/`.
- `POST /v1/search` and `POST /v1/evidence/search` require `snapshot_id` and `retrieval_profile_id`;
  no route tells a client which ones the server serves.

## Decision

1. **No hosted environment.** The recruiter-facing demonstration is a recorded video made on the
   owner's laptop, where live research runs use the GPU. Section 3.1 goal 16 becomes "provide a
   released, versioned image and a documented procedure that runs the demonstration environment";
   public hosting is optional future work and section 18.2's hosting choice stays OPEN.
2. **Serving lock.** A second locked environment, `environment-serving.yaml` and
   `environment-serving-linux-64.lock`, holds the test environment plus conda-forge `pytorch-cpu`
   2.14 and transformers 5.17.0, sentence-transformers 6.1.0, huggingface-hub 1.33.0, tokenizers
   0.23.2 and safetensors 0.8.0. The image is built from it and serves on CPU. CI tests keep the
   slim lock. The owner's GPU environment is documented as the serving lock with a CUDA torch build.
   Docling and the ingestion worker stay out of the image (backlog #115).
3. **Images and releases.** Images live at `ghcr.io/avsngh-git/ragpipeline` (public package, free).
   - A push to `main` that passes CI pushes `sha-<12-char commit>`.
   - A tag `vX.Y.Z` runs `release.yml`, which retags the tested `sha-` image for that commit as
     `vX.Y.Z` and `latest` without rebuilding, and creates a GitHub Release whose notes name the
     image digest.
   - The image contains `migrations/` and a `research-migrate` command; migrations run as an
     explicit step, never at API start.
   - Phase 6 releases are `v0.6.x`; the closeout release is `v1.0.0`.
4. **Demo bundle.** `research-demo export` writes a versioned bundle from the reviewed database
   with an allowlist: it copies only named tables and only the rows reachable from the accepted
   snapshot, its published generation and the showcase runs of one principal. It never copies
   API keys, LangGraph checkpoints, model-call payloads, experiments, discovery records, ingestion
   job state, other snapshots or runs of other principals. Layout:

   ```text
   research-demo-v1/
     manifest.json            bundle version, snapshot, generation, profile, models, runs, file sha256
     ATTRIBUTION.md           per-paper licence and source (ADR-0032)
     postgres/NN_<table>.csv.gz
     qdrant/<collection>.snapshot
   ```

   It is attached to the GitHub Release `demo-data-v1` as `research-demo-v1.tar` with a `.sha256`
   file. `research-demo load` verifies checksums, loads the rows into a freshly migrated database
   and restores the Qdrant snapshots. `research-demo fetch-models` downloads the pinned model
   revisions of the active profile. Showcase runs (6–10, both modes, including the section 2.5
   reference question and at least one insufficient-evidence run) are started on `main` with a key
   whose principal is `demo`.
5. **Small mode.** From a clean clone: `scripts/demo_load.sh` (pulls or builds the image, starts
   PostgreSQL and Qdrant, migrates, downloads and loads the bundle, fetches the models and creates
   a local `read` key for principal `demo`), then `docker compose up -d`, then the UI at
   `http://127.0.0.1:8000/`. It runs on CPU with no GPU and no accounts. Live research runs need the
   existing `llm` profile and an NVIDIA GPU, and are documented as optional. The local server uses
   the `trusted_private_local` evidence profile (ADR-0032 decision 6).
6. **Serving identity route.** `GET /v1/serving` (scope `read`) returns the served snapshot ID,
   retrieval profile ID and generation from `ResearchCapabilities.serving()`.
7. **Thin UI.** One static HTML page served at `GET /` from package data: no build step, no new
   dependency, no framework. It asks for an API key (kept in `sessionStorage`), and offers paper
   search, evidence search with passage text, and a research-run viewer reached by `#run=<run_id>` that
   shows each claim with its verified quote (the cited passage text), evidence handle and paper.
8. **Gate.** Phase 6 passes when:
   1. the `demo-smoke` workflow (manual and on release) follows the README quickstart literally on
      a fresh GitHub runner and its checks pass: readiness, a ranked paper search, an evidence
      search with text, every showcase run readable with claims, quotes and papers, and the eight
      MCP tools listed;
   2. a cold-reviewer agent given only the public repository follows the README and docs and
      reports every point that needed private knowledge; each finding is fixed or recorded as a
      limitation;
   3. the owner accepts the recorded video.

## Alternatives set aside

- **A free hosted demo** (Oracle Always Free, Cloud Run with Neon and Qdrant Cloud): a card on
  file, an arm64 build or an uncapped bill, data-deletion clocks and slow cold starts, against the
  owner's no-bills rule.
- **ML packages in the single test lock:** slower, heavier CI for no test benefit.
- **Image left as it is, small mode from a host Conda environment:** the released image could not
  serve the demonstration.
- **`pg_dump` of the review database with private tables deleted:** a forgotten table leaks.
- **Re-ingesting the corpus in small mode:** hours of GPU Docling time and different identifiers
  than the benchmark.
- **A framework UI (Streamlit, Gradio, React):** a new dependency or build step for one page.

## Consequences

- Section 22's "a versioned image is deployed to a real target" becomes "a versioned image is
  released and runs the documented demonstration environment".
- The image grows by the CPU PyTorch stack (an estimated 3.5–4 GB); the `demo-smoke` workflow runs
  manually and on release, not on every pull request.
- Retrieval in the image runs on CPU; scores can differ from the GPU host in the last digits.
  Benchmark numbers come from the recorded host runs, not from the small mode.
- Model weights are never in the image; `fetch-models` downloads pinned revisions from Hugging Face.
