# Phase 2 held-out acceptance report

**Status:** Phase 2 remains unaccepted. The fresh v9 assessment passed 13 of 14
frozen gates and missed paper nDCG@10 (0.7218 against the 0.80 minimum). P2-01–P2-19
and hosted CI are complete; P2-20 remains open.

## Decision

The v9 run is spent and sealed from selection. No v9 item-level result or metric was
used to select or tune another profile, and the frozen acceptance limits were not
changed. The development-selected MiniLM-over-Hybrid-E5 profile with reranker prefix
16 passed its evidence, source-coverage and operational gates but did not pass the
paper ranking gate. No development-supported repair to the locked paper aggregation
policy has yet been established. Phase 2 therefore remains unaccepted; Phase 3 has
not started.

Earlier assessments are also spent: v7 passed 12/14 gates (paper nDCG@10 and warm
p95 failed); v8 passed 13/14 (evidence direct MRR@10 failed); v9 passed 13/14 (paper
nDCG@10 failed). Their aggregate history is descriptive and cannot guide selection.
Any repair work must use development-only evidence. A subsequent acceptance attempt
requires a new independently source-reviewed held-out set and the unchanged gates.

## Frozen v9 inputs

| Field | Value |
| --- | --- |
| Assessment | `phase2-benchmark-v9`, ten held-out families |
| Selected profile | MiniLM reranking over Hybrid-E5, prefix 16 |
| Profile identity | `sha256:a546f01870ba76ce38dff5ba24520be76b88db49bde62b406a9124d55a3e3ceb` |
| Candidate review | 339 papers and 496 evidence passages; all resolved |
| Positive source review | Nine direct anchors; nine direct pooled-candidate links |
| Snapshot | Accepted 100-paper snapshot; fixed across profiles |
| Run record SHA-256 | `7ac6da19f765e655944576e19e6bcd99225fea5e66a2d38aaf140b7fa23dc24f` |

Question identities, raw rankings, candidate text, per-family results and run files
remain in the ignored private directory. This report contains sanitized aggregates
only. The 10-family set is purposive and supports directional evidence, not precise
population estimates.

## Aggregate profile comparison

| Profile | Paper nDCG@10 | Paper direct MRR@10 | Paper Recall@20 | Evidence nDCG@10 | Evidence direct MRR@10 | Evidence Recall@20 | Source Recall@10 / @50 | Warm p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 lexical | 0.5379 | 0.6905 | 0.9286 | 0.4116 | 0.5119 | 0.2786 | 0.4444 / 0.4444 | 604.8 |
| Dense E5 | 0.6233 | 0.9286 | 1.0000 | 0.3678 | 0.7857 | 0.5929 | 0.2222 / 0.3333 | 1,107.1 |
| Hybrid E5 | 0.7230 | 0.9286 | 1.0000 | 0.4121 | 0.6905 | 0.4619 | 0.4444 / 0.4444 | 1,269.3 |
| MiniLM over Hybrid E5 (selected) | 0.7218 | 0.9286 | 1.0000 | 0.5556 | 0.8214 | 0.7310 | 0.5556 / 0.7778 | 1,439.1 |
| Fixed-window dense E5 | 0.6939 | 0.9048 | 1.0000 | 0.3441 | 0.8571 | 0.3857 | 0.4444 / 0.4444 | 386.0 |

Latency uses 100 warm samples per profile. Source recall measures only the nine
independently reviewed anchors; it is not corpus-wide passage recall. Comparison
profiles are descriptive and were not used to select from the spent v9 set.

## Selected-profile acceptance gates

| Gate | Frozen limit | v9 aggregate | Result |
| --- | ---: | ---: | --- |
| Paper nDCG@10 | ≥ 0.80 | 0.7218 | Fail |
| Paper direct MRR@10 | ≥ 0.70 | 0.9286 | Pass |
| Paper judged Recall@20 | ≥ 0.90 | 1.0000 | Pass |
| Evidence nDCG@10 | ≥ 0.45 | 0.5556 | Pass |
| Evidence direct MRR@10 | ≥ 0.45 | 0.8214 | Pass |
| Evidence judged Recall@20 | ≥ 0.60 | 0.7310 | Pass |
| Source-anchor Recall@10 | ≥ 0.25 | 0.5556 | Pass |
| Source-anchor Recall@50 | ≥ 0.35 | 0.7778 | Pass |
| Positive source families with a hit at @10 | ≥ 0.50 | 0.5714 | Pass |
| Hard-failure fraction | ≤ 0.01 | 0.0000 | Pass |
| Reranker fallback fraction | ≤ 0.35 | 0.0000 | Pass |
| Warm p95 | ≤ 1,500 ms | 1,439.1 ms | Pass |
| Combined cold model load | ≤ 15,000 ms | 5,998.8 ms | Pass |
| Summed CUDA allocation | ≤ 1 GiB | 224,966,656 bytes | Pass |

The local runtime was an NVIDIA GeForce RTX 3050 Laptop GPU exposed through WSL.
Unsupported-query rejection remains disabled. Returned-hit behavior and evidence
requirement-group coverage are descriptive; they are not converted into rejection
accuracy. Group piece coverage was 0.5556 at rank 10 and 0.7778 at rank 50; complete
group fractions were 0.5714 and 0.7143, respectively, with no predeclared numeric
gate.

## Next step

P2-20 stops at the failed paper nDCG gate. Investigate candidate ranking using only
the existing calibration and development sets, while preserving the locked strongest-
passage paper aggregation rule and all acceptance limits. Record whether development
evidence supports a concrete profile change. Do not inspect or tune from any spent
held-out item-level result. If a justified profile change is made, freeze it before
building and scoring a new source-reviewed held-out set.
