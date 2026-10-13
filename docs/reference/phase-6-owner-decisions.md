# Phase 6 owner decisions

**Status:** record of the owner's judgement calls during Phase 6, kept for later analysis.
Each entry gives the date, what was decided, the evidence it rested on, the alternatives
set aside, and what to re-examine later.

## Owner decisions

### 1. Planning interview (2026-10-13)

The owner answered 17 questions over four rounds and accepted the assistant's recommendation on
each, except Q4 (cost) and Q16 (hosting), where the owner ruled out any bill and made the public
demo optional. [ADR-0032](../adr/0032-phase6-public-cc-by-demo-collection.md) and
[ADR-0033](../adr/0033-phase6-delivery-without-hosting.md) record the design; the
[plan](../plans/phase-6-portfolio.md) lists the cards.

Evidence available at the time:
- **Spec:** section 21 Phase 6 deliverables and gate; section 3.1 goal 16 and section 22 require a
  deployed environment; section 18.2 allows a local-model demonstration paired with a hosted subset.
- **Rights:** all 103 permission records of the 102 documents in `research_phase1_review` are
  `cc-by`; display was off by choice. The NC-ND and personal-use files sit outside every snapshot.
- **Hosting (checked 2026-10-13 against official pages):** Hugging Face Docker Spaces need PRO
  ($9/month) and block outbound ports other than 80, 443 and 8080; Oracle Always Free gives
  2 Arm OCPUs and 12 GB but needs a card; Cloud Run's free tier has no hard spend cap; Qdrant Cloud
  free clusters are deleted after four idle weeks; Render, Koyeb, Fly and Railway are too small or
  not free; GHCR is free for public packages.
- **Code:** CI never pushes images; the locked environment lacks PyTorch, transformers and
  sentence-transformers, which the host environment has outside the lock; migrations are not in
  the image; the API starts and reports ready without Ollama.

| # | Topic | Decision | Alternatives set aside |
| --- | --- | --- | --- |
| Q1 | Scope | Deployment and portfolio only. Backlog #115, the unmerged local candidates and the 100K context stay out; the failure analysis reports the answer-quality gap | Taking #115 items into Phase 6 |
| Q2 | Public corpus | A public CC BY demo collection with passage display (ADR-0032) | Text withheld; deploying the private corpus |
| Q3 | Environment shape | A hosted backend subset with runs computed on the laptop (later superseded by Q16) | On-demand GPU; CPU generation; laptop tunnel |
| Q4 | Cost | No bills at all: "this is only a showcase project" | About €20/month for a VM |
| Q5 | UI | One static HTML page served by FastAPI | No UI; Streamlit or Gradio |
| Q6 | Images and releases | GHCR; `sha-` images from `main`; `vX.Y.Z` retags the tested digest; GitHub Releases | Rebuilding on tag |
| Q7 | Documentation | README rewritten as the portfolio front page; phase log to `docs/history.md`; architecture, benchmarks, failure analysis and operations documents | Appending to the current README |
| Q8 | Which corpus | The accepted 100-paper snapshot itself, after a per-document CC BY check | A 10–30 paper subset |
| Q9 | Public access | A published read-only demo key (dropped with Q16) | Anonymous read; keys on request |
| Q10 | Showcase runs | 6–10 runs on `main`, both modes, including the reference question and an insufficient-evidence run, started by principal `demo`; no model-call payloads | — |
| Q11 | Building the bundle | Allowlist export into a versioned bundle attached to a GitHub Release | `pg_dump` with deletions; re-ingesting |
| Q12 | Small mode | `scripts/demo_load.sh`, `docker compose up`, UI on CPU; live runs optional with the `llm` profile and a GPU | — |
| Q13 | Gate | `demo-smoke` workflow, cold-reviewer pass, owner review (the post-deploy check dropped with Q16) | — |
| Q14 | Video | A 3–5 minute recording by the owner from an agent-written script | — |
| Q15 | Hosted observability | JSON logs only (dropped with Q16) | — |
| Q16 | Hosting | **No hosted environment.** "Make this public demo thing optional. I do not want any bills. Just a video demonstration for recruiters would be enough which can be done just using my laptop." Changes LOCKED goal 16 (ADR-0033) | Oracle Always Free; Cloud Run with Neon and Qdrant Cloud; Hugging Face PRO |
| Q17 | ML stack in the image | A second, serving lock with CPU PyTorch and the host's model library versions; CI keeps the slim lock | One lock with everything; leaving the image unable to serve |

Re-examine later: whether a free host appears that fits; whether the CPU image's rankings match
the GPU host closely enough to say so in the README.
