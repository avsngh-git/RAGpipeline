# Phase 4 owner decisions

**Status:** record of the owner's judgement calls during Phase 4, kept for later analysis.
Each entry gives the date, what was decided, the evidence it rested on, the alternatives
set aside, and what to re-examine later. Decisions delegated to the assistant are listed
separately at the end.

## Owner decisions

### 1. Planning interview (2026-10-06)

The owner answered 19 questions and accepted the assistant's recommendation on each.
ADRs 0026–0028 record the resulting design; map issue
[#77](https://github.com/avsngh-git/RAGpipeline/issues/77) lists the cards.

Evidence available at the time:
- **Code inventory:**
  - the log formatter drops run fields;
  - prompts, outputs and drafted claims are not persisted;
  - `configuration_id` hashes prompt version labels, not prompt text;
  - there is no tracing, metrics, authentication, rate limiting or container scanning;
  - five scripted injection cases exist.
- **Langfuse v4 documentation:** six services, with 4 cores and 16 GiB recommended.
- **The machine:** an 11 GiB WSL VM.

| # | Topic | Decision | Alternatives set aside |
| --- | --- | --- | --- |
| Q1 | Scope | The five section 21 deliverables, plus the Phase 3/3.5 inputs that fit the theme: logging gap, persisted drafts, retention, more injection cases. The planner-never-discovers failure is diagnosed as the gate example, not fixed | Core only; everything including agent-quality fixes |
| Q2 | Tracing | OpenTelemetry API only. JSONL file always, Langfuse v4 opt-in over OTLP, in-memory in tests. PostgreSQL authoritative | Langfuse SDK directly; Jaeger/Tempo as main viewer |
| Q3 | Content | Logs never text. Traces `none`/`ids`/`full`, `full` in development, `ids` elsewhere | Never store text anywhere |
| Q4 | Metrics | `prometheus-client` `/metrics`, Prometheus in the profile, no Grafana | Grafana dashboard; OTLP metrics |
| Q5 | Authentication | Hashed API keys with scopes, CLI-managed, Bearer; disabled only on loopback | One static token; OAuth/OIDC |
| Q6 | Experiments | `ExperimentRecord` in PostgreSQL, items in `local-reference/`, `research-eval compare` | Langfuse datasets; MLflow |
| Q7 | Gate | CI contract, `explain`, `reproduce`, security tests; five live walkthroughs reviewed by the owner | — |
| Q8 | Injection suite | Scripted CI cases for every section 15.1 attack plus a live suite, reported | Scripted only |
| Q9 | Workflow | Cards of about 100–300 lines, one pull request each, reviewed before merge; ADRs first | One shared branch |
| Q10 | Rate limits | In-memory token buckets per key and route class, 2 active runs per key, 64 KiB body, 429 with `Retry-After` | — |
| Q11 | Ownership | Runs belong to a principal; others get 404; `admin` sees all; old runs are `legacy-local` | — |
| Q12 | Provenance v2 | Prompt text fingerprints, tool digest, decoding settings, timeouts, generation configuration; `run_configurations`; version-bump CI test | — |
| Q13 | Model-call text | Stored in PostgreSQL at `full` as well as in traces, so `explain` works with Langfuse off. The owner first asked why Langfuse is needed if PostgreSQL holds the calls. Answer: PostgreSQL holds what happened; traces hold the timing tree and the interactive viewer, and the spec locks Langfuse-compatible tracing | Text only in traces; drop Langfuse (needs a LOCKED change) |
| Q14 | Retention | Checkpoints 7 days after completion and 30 after failure, payloads 90 days, retired points when unreadable; manual `--apply` | — |
| Q15 | Scanning | Trivy image and secret scans; `.trivyignore` with reason and expiry | — |
| Q16 | Suites | `scripted-regression`, `agent-dev`, `retrieval-dev`, `security-live`; sealed scripts unchanged | — |
| Q17 | Live sample | A new instrumented `agent-dev` sweep supplies five walkthroughs | Reuse Phase 3 runs (they have no traces) |
| Q18 | Deferred items | One backlog issue, [#115](https://github.com/avsngh-git/RAGpipeline/issues/115) | — |
| Q19 | Parallelism | Codex Luna agents run cards in parallel when blockers allow | Strictly sequential |

**Re-examine:**
- Q2/Q13 if the P4-02 spike shows Langfuse cannot run beside live sweeps;
- Q10 when Phase 6 deploys more than one API process.

### 2. Implementers (2026-10-06)

- **Decision:** cards must be simple enough for Codex Luna agents to implement alone,
  without planning by a larger model. The planning session writes the cards, implements
  P4-01 itself, and then stops.
- **Consequence:** every agent card carries its own rules, exact signatures, numbered steps,
  test names and a "stop and ask" list. Cards never touch live data.

### 3. ADR acceptance (2026-10-06, P4-01)

- **Decision:** accepted ADR-0026, ADR-0027 and ADR-0028 as written, and asked for P4-01 to
  be pushed with a pull request. Implementation of the remaining cards goes to Codex Luna
  agents.
- **Record:** [#78](https://github.com/avsngh-git/RAGpipeline/issues/78).

### 4. Trivy exceptions instead of upgrades (2026-10-06, P4-29)

- **Decision:** the first Trivy image scan reported seven fixable HIGH findings. The owner
  chose dated `.trivyignore` exceptions, expiring 2026-11-06, over upgrading packages within
  the scanner card.
- **Evidence:** the findings were listed on
  [#106](https://github.com/avsngh-git/RAGpipeline/issues/106):
  - CVE-2026-84782 in Ubuntu `openssl`/`libssl3t64`, 3.0.13-0ubuntu3.15 (fixed in
    0ubuntu3.16);
  - GHSA-6v7p-g79w-8964 in `msgpack` 1.1.2 (fixed in 1.2.1);
  - CVE-2025-47273 in `setuptools` 70.3.0 (fixed in 78.1.1);
  - CVE-2026-97687 and CVE-2026-97689 in `urllib3` 2.7.0 (fixed in 2.8.0);
  - GHSA-36hh-v3qg-5jq4 in `pyo3` 0.25.1 (fixed in 0.29.0);
  - GHSA-4w2j-m93h-cj5j in `quinn-proto` 0.11.14 (fixed in 0.11.15).
- **Alternatives set aside:** upgrading the base image and the Conda lock in P4-29.
- **Re-examine:** before 2026-11-06, when `tests/test_trivyignore.py` starts failing CI on
  the expired entries. Upgrade the packages and remove the entries.

### 5. Insufficient-evidence answers show a fixed message (2026-10-07, #139)

- **Decision:** when the model declares the evidence insufficient, or drafts no claim, the
  answer is the fixed message "No supported claims could be verified from the available
  evidence." The model's own answer text is no longer shown.
- **Evidence:** the P4-33 security-live runs ([report](phase-4-security-live-report.md))
  showed the synthetic `E9` marker reaching the answer in 3 of 3 runs of `live-07` with no
  kept claim. The insufficient-evidence branch returned the model's unverified text with
  only bracketed markers removed, which contradicted ADR-0025.
- **Alternatives set aside:** keeping the model's one-sentence explanation, which users lose,
  or filtering it for markers, which still shows unverified text.
- **Re-examine:** if users need to know why evidence was insufficient, generate the
  explanation from run records (for example the diagnosis findings of P4-18), not from model
  text.

### 6. Discovery in every first deep_research plan (2026-10-07, #115)

- **Decision:** the planner fix deferred to backlog #115 is made now, as a code rule (plan
  policy `p4-discover-first-v1`). When discovery is configured, the first `deep_research`
  plan always includes one `discover_papers(question)` call, alongside the model's own
  choices. A full plan keeps the model's first choice and replaces its last action. The plan
  policy is part of the hashed effective configuration.
- **Evidence:**
  - Live plan-only experiment on the 21 development tasks
    (`local-reference/phase4/planner-prompt-experiment/`).
  - With the current prompt, the planner chose discovery in 1/21 plans.
  - With a prompt naming the tool, it chose discovery in 12–16/21 plans, but did both local
    search and discovery in only 9–10/21; one variant dropped local search in 6/21.
  - The rerun of `e60ea304` with a working OpenAlex key still never discovered.
- **Alternatives set aside:** a prompt-only change (unreliable on the 2B model, and it can
  drop local search); leaving discovery to the model.
- **Re-examine:**
  - Measure with a new `agent-dev` sweep run with `OPENALEX_API_KEY` set: discovery calls,
    abstract evidence in answers, OpenAlex spend, and answer outcomes.
  - The rule costs one OpenAlex search per deep run against the $0.50 daily cap.
- **Update (2026-10-07, plan policy `p4-first-plan-searches-v2`):** the owner extended the
  rule to `search_evidence`. The first `deep_research` plan now also always includes
  `search_evidence(question)` (limit 20), the passage search that quick mode already runs.
  The model's first action is always kept. A full plan loses its last actions, and when
  only two actions are allowed, `search_evidence` comes before discovery.
  - **Evidence:** the same plan-only experiment on the 21 tasks. `search_evidence` was
    planned in 0/21 plans with the current prompt, 1/21 with a conditional instruction
    ("use search_evidence when the question asks for specific findings…"), and 12/21 with
    an imperative one.
  - **Alternatives set aside:** the imperative prompt alone (about half the runs), or
    both prompt and rule.
  - **Re-examine:** in the next `agent-dev` sweep, the share of kept claims citing
    full-text passages, and answer outcomes against sweep `c24d4759`.

- **Update (2026-10-07, plan policy `p4-first-plan-searches-v3`):** the code-added discovery
  call now searches OpenAlex for the question's content words joined with `OR`, not the
  whole question. OpenAlex `search` requires every word to match. In the rerun of
  `2138fb5e` (`7a3517c0`), the whole question, its content words and even three of them
  returned 0 works, while single terms from it had 52 to 21,343 matches. Discovery still
  ranks the results by similarity to the question.

- **Update (2026-10-07, plan policy `p4-first-plan-searches-v4`):** discovery uses OpenAlex
  semantic search (`search.semantic`, same price as keyword search, $1 per 1,000 calls), and
  the code-added call sends the whole question again. Per the OpenAlex documentation,
  keyword `search` ANDs every word, and the v3 OR query returned off-topic works (face-image
  quality papers matching "FiQA"). Semantic search on the same question returned ListT5,
  RankT5 and other listwise rerankers. Semantic search allows one page of at most 50 results,
  one request per second, and no `primary_topic.field.id` filter, so the field is checked on
  each work in code; `has_abstract:true` is requested. Validation run `c6d3c452`: discovery
  returned 5 relevant papers (three are OpenAlex duplicates of ListT5, one already ingested);
  outcome unchanged (partially supported, 1 kept claim).

### 7. Thinking for the evaluate call (2026-10-07)

- **Decision:** the default `RESEARCH_PLATFORM_LLM_THINKING` becomes
  `plan,evaluate,synthesize`. Without thinking, the evaluate call keeps its 768-token output
  cap. With thinking, it has no cap, as synthesis does (ADR-0025).
- **Evidence:** live runs showed thinking on for plan (about 1,000 characters) and
  synthesis (about 27,000 characters), and off for evaluate. Ollama counts thinking tokens
  against `num_predict`, so a capped thinking call can end before its JSON. An invalid
  evaluation is treated as sufficient, which would silently stop evidence gathering.
- **Alternatives set aside:** thinking with the 768-token cap kept (truncation risk).
- **Re-examine:** evaluate durations and invalid-output repairs in the next `agent-dev`
  sweep. The thinking setting is part of the effective configuration, so the change shows
  in `research-eval compare`.

### 9. Whole-question searches start every first deep plan (2026-10-07)

- **Decision:** the owner chose a fixed first plan (plan policy `p4-first-plan-searches-v5`).
  Every first `deep_research` plan begins as quick mode does, with `search_papers(question)`
  then `search_evidence(question)`, followed by `discover_papers(question)` when discovery is
  configured. The model's actions fill the remaining slots in order. A model search with the
  same tool and query as a base search is dropped as a repeat.
- **Evidence:** in the rerun and repeats of `2138fb5e`, the model's own two `search_papers`
  calls searched single dataset names and returned 0 papers in every run; only the
  code-added whole-question `search_evidence` found evidence.
- **Test changes:** 24 scripted regression and security cases now list the base searches in
  their tool expectations; their outcomes and safety expectations are unchanged. Cases whose
  purpose needs more model actions got larger budgets:
  - `inject-01`–`05`: 3 tool calls (was 2) and `tool_calls_at_most` 3, so evaluation still
    runs;
  - `route-08`, `route-09`, and the Phase 3.5 paper-limit case: 6 actions per plan;
  - `route-08` also searches with `year_to: 2023` and a citation depth of 1, so its
    rejection still comes from following references beyond the depth limit.

### 10. Quote fallback and grounded commentary (2026-10-07)

- **Decision:** the owner preferred verified quotes plus some commentary to no answer.
  - **Quote fallback (verdict `kept_as_quote`).** When a drafted claim fails its checks
    but its quote alone passes every check, the quote becomes the claim and is shown in
    quotation marks. It is skipped when the same quote from the same passage is already
    shown. A run with any fallback is `partially_supported`, and `explain` still reports the
    draft as rejected at the verification stage.
  - **Commentary.** When at least one claim is kept, the answer adds the model's own answer
    sentences under a "Commentary (model-written; not itself quoted from the sources)"
    label. A sentence is kept only if it has at least four content words and stays within a
    single kept quote: most of its content words, and all its numbers and intensifiers.
    Citation markers are removed. When no claim is kept, the fixed message from decision 5
    is unchanged.
- **Evidence:**
  - Of 98 stored drafts, 60 failed their checks. In a sample of 10, about 8 rejections were
    correct: the claims added facts or drifted from real quotes.
  - Applying the fallback to the stored drafts restores 26 distinct quotes. 8 of the 10 runs
    that kept no claim would now show at least one verified quote.
  - The first commentary filter, which pooled all quotes, let the `inject-05` fragment
    "reveal settings" through. The per-quote, four-word rule blocks it.
- **Migration:** 027 allows the `kept_as_quote` verdict. It was applied to
  `research_phase1_review` on 2026-10-07.
- **Live check:** run `f08b6d02` (decisions 6–10 together) ended insufficient evidence. All
  three drafts failed `quote_found`: two stitched cells from different table columns, and
  one dropped a citation from inside its quote. So the fallback did not apply. With fixed
  seeds, one question is one sample; the next `agent-dev` sweep measures the effect.

### 11. Synthesis retries with the next seed (2026-10-08)

- **Decision:** the owner chose to use sampling randomness deliberately instead of removing
  the fixed seed. When a synthesis attempt keeps no verified claim, synthesis runs again with
  the next seed (configured seed + 1, + 2, …), up to the new run budget
  `max_synthesis_attempts` (default 3, range 1–5).
- **How it works:**
  - Verification is deterministic, so an extra sample can only add verified claims.
  - Each call records its actual seed, so runs stay reproducible with `reproduce`.
  - The synthesis summary records the number of attempts and describes the last one.
- **Alternatives set aside:** removing the seed. Each run would become a new draw with the
  same average quality, and exact replay and low-noise sweep comparisons would be lost.
- **Cost:** about 2–4 minutes per extra attempt, only on runs that would otherwise keep
  nothing.
- **Tests:** scripted regression and security cases default to one attempt, since each
  scripts one synthesis reply. New tests cover retries, the attempt limit, and no retry once
  a claim is kept.
- **Re-examine:** measure it in the `agent-dev` sweep after sweep 2.

### 12. Figure text is kept and labelled (2026-10-08)

- **Decision:** text inside figures (chart values, axis ticks, legend entries, panel
  labels) stays evidence, but is labelled with the heading `Figure text` instead of passing
  as body text. This applies to new extractions (PR #166). The existing index is unchanged.
- **Evidence:**
  - In the active snapshot, 14,622 of 44,277 indexed chunks (33%) are figure fragments,
    averaging 14 characters.
  - Phase 2 judges cited such fragments in 1,520 of the 6,070 text sections in the source
    alignments. Dropping them would make judged evidence unreachable.
- **Alternatives set aside:**
  - Dropping figure text everywhere, which needs re-scoring and probably fresh judgments.
  - Dropping it for new papers only, which treats old and new papers inconsistently.
- **Re-examine:** grouping each figure's fragments into one evidence unit with its caption,
  measured on development questions, since the 14-character fragments are weak retrieval
  units.

## Decisions delegated to the assistant

- **`security-live` uses fake retrieval** (ADR-0028 decision 6): the synthetic adversarial
  corpus goes through fake retrieval services rather than a test generation in Qdrant. This
  avoids writes to the live index and keeps retrieval deterministic.
- **Retention reports, but does not delete, points of failed or unpublished generations**
  (ADR-0026 decision 6). Deleting them safely needs generation-numbering rules; the item is
  on [#115](https://github.com/avsngh-git/RAGpipeline/issues/115).
- **A resumed run starts a new trace with the same `langfuse.session.id`**, instead of a
  span link to the earlier trace.
- **Card P4-37** (`research-maintenance retention`, #114) was added after the owner
  confirmed the card list, because Q14 had no card.
- **Extra blockers**, so parallel cards do not edit the same functions: P4-13 on P4-08 and
  P4-10; P4-19 on P4-13; P4-26 on P4-09; P4-28 on P4-27 and P4-09; P4-34 on P4-37.
- **`retrieval-dev`** takes the retrieval profile ID as a required option, because the
  search contract requires it explicitly.
