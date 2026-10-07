# Phase 4 gate report

**Status:** prepared 2026-10-07. Items 1, 2, 3 and 5 pass in CI; gate item 4 awaits the
owner's walkthrough review.

This report records the five items from ADR-0028. The live development walkthroughs and
their supporting traces remain private under `local-reference/phase4/walkthroughs/` and
`local-reference/traces/p4-34/`. No question, answer, prompt, passage, or model payload text
is reproduced here.

## Gate items

1. **Trace and log contract — passed in CI.** P4-17's ten contract checks passed in
   [CI run 37603023275](https://github.com/avsngh-git/RAGpipeline/actions/runs/37603023275).
2. **`research-runs explain` — passed in CI.** P4-18's scripted stage-diagnosis checks
   passed in [batch CI run 37598135293](https://github.com/avsngh-git/RAGpipeline/actions/runs/37598135293).
3. **`research-runs reproduce` — passed in CI.** P4-19's configuration hash and scripted
   rerun checks passed in [batch CI run 37598135293](https://github.com/avsngh-git/RAGpipeline/actions/runs/37598135293).
4. **Five live development walkthroughs — prepared; owner review pending.** The five runs
   below span three diagnosis stages. All five `research-runs reproduce` invocations exited
   0, with matching hashes, rebuilt configurations, and no differences. The owner should
   review the full walkthrough at
   `local-reference/phase4/walkthroughs/2138fb5e-d591-494c-bc16-35126b200311.md` and record
   the judgement in `phase-4-owner-decisions.md` before this item is marked passed.

   | Run | Mode / outcome | Stage | Trace finding |
   | --- | --- | --- | --- |
   | `bb66f853-ba99-44d0-b9c4-0345fbaf834d` | deep research / insufficient evidence | evidence | 17 passages were collected and shown; synthesis declared the evidence insufficient; planner used `search_papers` without discovering papers. |
   | `2138fb5e-d591-494c-bc16-35126b200311` | deep research / insufficient evidence | verification | Three claim checks failed; tool path used `search_papers` and `search_evidence`; planner-never-discovered finding present. |
   | `e60ea304-6d9c-46ae-8511-4b540b513025` | deep research / insufficient evidence | retrieval | Five `discover_papers` calls failed and no evidence was collected. The failures were `discovery_unavailable` in 0 ms: the P4-34 API ran without `OPENALEX_API_KEY`, so no discovery service was configured. Rerun with the key (`2fd98e38-9595-437a-b457-7938a9132607`): discovery was available, but the planner chose only `search_papers`; stage verification (three drafts failed quote checks); `reproduce` exited 0. |
   | `a674580c-de86-4427-95e5-1d1a4ffab2f7` | quick / partially supported | verification | One drafted claim was rejected by the quote-to-row check and one was kept. |
   | `1a309247-9fa5-431d-b261-fcf3ea6d9369` | quick / insufficient evidence | evidence | 11 passages were collected and shown with none omitted; synthesis declared the evidence insufficient. |

5. **Security, authentication, ownership, and rate limits — passed in CI.** P4-26 in
   [batch run 37598135293](https://github.com/avsngh-git/RAGpipeline/actions/runs/37598135293),
   P4-27 in [run 37603848526](https://github.com/avsngh-git/RAGpipeline/actions/runs/37603848526),
   P4-28 in [run 37623184990](https://github.com/avsngh-git/RAGpipeline/actions/runs/37623184990),
   P4-30 in [run 37584792897](https://github.com/avsngh-git/RAGpipeline/actions/runs/37584792897),
   the unknown-paper injection case in
   [run 37610163470](https://github.com/avsngh-git/RAGpipeline/actions/runs/37610163470), and
   P4-31's API-attack and run-limit cases in
   [run 37641345219](https://github.com/avsngh-git/RAGpipeline/actions/runs/37641345219).

## Independent verification

The planning session re-ran `research-runs explain --json` and `research-runs reproduce` on
the five runs from merged `main` (`8f3e471`) against `research_phase1_review`. Stages, findings
and draft verdicts matched the table above, and all five reproductions exited 0. Caveat: online
discovery was not configured during the P4-34 sweep (see `e60ea304`), which limits what the
sweep can show about discovery. The rerun of `e60ea304` with the OpenAlex key set (verified working) still planned only local
search, which supports the planner diagnosis below.

## Planner diagnosis

The repeated local-search choice is consistent with the `p3-plan-v1` prompt: it prioritizes
`search_papers` and `search_evidence`, and makes `discover_papers` conditional on local
evidence being insufficient and external candidates being helpful. In the inspected
deep-research trace for run `2138fb5e-d591-494c-bc16-35126b200311`, the saved plan output
contains `search_papers` and `search_evidence` tool names, with no `discover_papers` or
`request_ingestion`; its thinking text references local-search names multiple times and
`discover_papers` once. The same run's later evaluation did not add a discovery call. Its
prompt fingerprints identify the plan and evaluation versions; the trace tree records the
plan and evaluation timings in the private walkthrough.

This evidence points to a prompt and decision-policy weakness: discovery is framed as a
conditional exception to the preferred local-search path, without an explicit, testable
criterion for when local coverage is inadequate. The finding is diagnostic only. Planner
changes remain in backlog issue [#115](https://github.com/avsngh-git/RAGpipeline/issues/115)
and are outside P4-35.
