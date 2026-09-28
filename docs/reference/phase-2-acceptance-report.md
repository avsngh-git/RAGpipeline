# Phase 2 held-out acceptance report

**Status:** The corrected v4 held-out assessment failed two frozen gates; Phase 2 is not accepted.

**Review:** Assistant-reviewed, 2026-09-28. The serving profile and numerical thresholds were unchanged during this assessment.

## Decision

The ten-family v4 assessment passed 12 of 14 frozen gates. Paper nDCG@10 was 0.7455 against a minimum of 0.80, and warm p95 was 1,533.96 ms against a maximum of 1,500 ms. The other quality, source-coverage, failure, fallback, model-load and GPU-memory gates passed.

A pre-scoring coverage audit found that the first paper review pool did not cover all returned top-50 paper candidates. We added 99 papers pooled across the five frozen profiles, removed profile/rank/score provenance, shuffled the supplement, and reviewed it with the existing 0/1/2 rubric. All five saved rankings were rescored against the completed common pool. This changed no retrieval order, profile, threshold or latency sample. Corrected paper judgment coverage is 100% for every profile; the original warm timing measurements are retained.

P2-20's assessment work is complete, but its Done condition requires every frozen gate to pass. Phase 2 therefore remains unaccepted. Do not tune on v4 or present it as an unseen test. Follow-up selection must use development data and a newly frozen held-out set.

## Frozen inputs and implementation identity

| Input | Identity |
| --- | --- |
| Accepted snapshot | `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` |
| Snapshot selection | `sha256:cc5b7c30962ce66ad279a5ff95b0e1e6dd8aede68980292717d1a7a23ecd6f18` |
| Dataset | `phase2-benchmark-v4`, 10 held-out families |
| Question manifest SHA-256 | `5895890c8a0cd7ab784ce2965e4689d0cb5e003b0dc0e01f33fa27fd76e85df2` |
| Split manifest SHA-256 | `e1bc1b9225f467f540e7968394aae1f797c9b03b9784c9b44586bfe0270585ae` |
| Source review SHA-256 | `d697be538c0a045e444d14e50bf152c73da8737a5f7604dc383e0a5fc4be5390` |
| Corrected source judgments SHA-256 | `d47f5df784f747ee89a81a1001cc46d8ca7bab437934eeba5e443a9f86d5306e` |
| Source chunk mapping SHA-256 | `b1739a120010ab024486231d4d39ef1da4f3e9ae21cda1b556609ef1777669c5` |
| Corrected pool manifest SHA-256 | `b9bdd5d1550fa0c6d5207015c56477027fa75091fcdfdcb7d7371dd7302035e0` |
| Sanitized frozen profile file SHA-256 | `a046992eef194f0966386f139a57ad7f0082a3fdfb989f42804f8546e3dfe522` |
| Serving profile ID | `sha256:3a8b4b57638d025405f276ddc22f9e5593f99e2807f40ee2c0e7a3fea8df7692` |
| Acceptance configuration SHA-256 | `133ce33507f52ca89ba96e7437d44352f78b96eb65155f67e551c28096cf20ae` |

The question manifest and all item-level review and result records remain in the ignored private `local-reference/phase2-runs/benchmark-v4/` tree. This report contains aggregate counts and metrics only.

## Benchmark, labels and source matching

The ten held-out families cover discovery (3), specific evidence (10), table results (3), cross-paper comparison (3), filters (6) and missing evidence (3). Categories overlap. The set is purposive and limited to the accepted 100-paper snapshot.

The final common review pool contains 348 paper candidates and 418 evidence candidates. Every candidate has a resolved assistant judgment:

| Pool | Candidates | Label 0 | Label 1 | Label 2 | Judgment coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Papers | 348 | 269 | 69 | 10 | 100% |
| Evidence | 418 | 269 | 111 | 38 | 100% |

The evidence source map contains 18 anchors (12 direct and 6 contextual) and 15 anchor-to-candidate links. Seven evidence requirement groups record multi-part questions. Text matches require at least 80% coverage of annotated spans; table matches require the identified row and its header/context checks. Candidate relevance scores and exact source-anchor matches are reported separately.

Paper nDCG@10 and paper judgment coverage use the common fully reviewed candidate pool. Evidence nDCG@10, MRR and judged recall use uniquely credited reviewed evidence candidates. Source-anchor recall credits exact canonical prose spans or validated table context across the returned chunks. Recall denominators include only eligible direct-positive judgments. No unsupported-query rejection cutoff is enabled; returned-hit counts are descriptive.

## Retrieval results

Quality values are macro means over ten families for nDCG and over the seven answerable families for MRR and judged recall. Source-anchor recall is micro-aggregated over 12 direct anchors. Judgment coverage is micro-aggregated over returned results.

| Profile | Paper nDCG@10 | Paper MRR@10 | Paper Recall@20 | Evidence nDCG@10 | Evidence MRR@10 | Evidence Recall@20 | Source Recall@10 / @50 | Warm median / p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 | 0.6956 | 1.0000 | 1.0000 | 0.4434 | 0.3929 | 0.4633 | 0.5000 / 0.5833 | 393.1 / 546.5 |
| Dense E5 | 0.6825 | 1.0000 | 0.9286 | 0.5515 | 0.8571 | 0.6612 | 0.5833 / 0.6667 | 698.4 / 900.8 |
| Hybrid E5 | 0.7393 | 1.0000 | 1.0000 | 0.5674 | 0.7857 | 0.5122 | 0.5833 / 0.6667 | 1,015.8 / 1,160.6 |
| MiniLM reranked Hybrid E5 | 0.7455 | 1.0000 | 1.0000 | 0.6948 | 0.8571 | 0.7769 | 0.7500 / 0.7500 | 1,174.9 / 1,534.0 |
| Fixed-window dense E5 | 0.7445 | 1.0000 | 0.9286 | 0.4360 | 0.7619 | 0.5503 | 0.6667 / 0.6667 | 185.2 / 360.7 |

Judgment coverage is 100% for both paper and evidence outputs across all five profiles after the pool correction.

### Paired family bootstrap

Each value is the selected profile minus the named baseline, with a 95% percentile interval from 10,000 family-resampled draws. nDCG uses ten families; MRR and recall use seven answerable families; source recall uses seven positive-source families.

| Baseline | Paper nDCG@10 | Evidence nDCG@10 | Source Recall@10 | Source Recall@50 |
| --- | --- | --- | --- | --- |
| BM25 | +0.0499 [-0.0077, +0.1092] | +0.2513 [+0.1318, +0.3671] | +0.2857 [+0.0714, +0.5714] | +0.2143 [0.0000, +0.5000] |
| Dense E5 | +0.0630 [-0.0091, +0.1470] | +0.1433 [+0.0861, +0.2140] | +0.1429 [0.0000, +0.2857] | +0.0714 [0.0000, +0.2143] |
| Hybrid E5 | +0.0062 [+0.0012, +0.0120] | +0.1274 [+0.0411, +0.2240] | +0.2143 [0.0000, +0.5000] | +0.1429 [0.0000, +0.4286] |
| Fixed-window dense E5 | +0.0010 [-0.0929, +0.0988] | +0.2588 [+0.1889, +0.3384] | +0.0714 [0.0000, +0.2143] | +0.0714 [0.0000, +0.2143] |

| Baseline | Paper MRR@10 | Paper Recall@20 | Evidence MRR@10 | Evidence Recall@20 |
| --- | --- | --- | --- | --- |
| BM25 | +0.0000 [0.0000, 0.0000] | +0.0000 [0.0000, 0.0000] | +0.4643 [+0.1071, +0.7500] | +0.3136 [+0.0898, +0.5850] |
| Dense E5 | +0.0000 [0.0000, 0.0000] | +0.0714 [0.0000, +0.2143] | +0.0000 [-0.2857, +0.2857] | +0.1156 [+0.0408, +0.2000] |
| Hybrid E5 | +0.0000 [0.0000, 0.0000] | +0.0000 [0.0000, 0.0000] | +0.0714 [-0.2143, +0.4286] | +0.2646 [+0.0810, +0.5265] |
| Fixed-window dense E5 | +0.0000 [0.0000, 0.0000] | +0.0714 [0.0000, +0.2143] | +0.0952 [0.0000, +0.2381] | +0.2265 [+0.0714, +0.3714] |

The ten-family intervals are wide. These results support directional comparison on this snapshot, not a general superiority claim.

### Category view for the selected profile

| Category | Families | Paper nDCG@10 | Evidence nDCG@10 | Source Recall@10 |
| --- | ---: | ---: | ---: | ---: |
| Discovery | 3 | 0.8634 | 0.6556 | 0.6000 |
| Specific evidence | 10 | 0.7455 | 0.6948 | 0.7500 |
| Table results | 3 | 0.9240 | 0.8606 | 1.0000 |
| Cross-paper comparison | 3 | 0.8846 | 0.6445 | 0.6667 |
| Filters | 6 | 0.8937 | 0.7581 | 0.8000 |
| Missing evidence | 3 | 0.4360 | 0.6061 | Not defined |

These overlapping category aggregates are descriptive and are not separate gates.

### Missing-evidence returned-hit profile

The cutoff remains disabled, so this is not rejection accuracy. Across three missing-evidence families, the selected profile returned 150 paper hits and 73 evidence hits at the 50-result quality limit; two evidence hits matched reviewed source anchors. This bounded sample does not establish corpus-wide absence.

## Frozen acceptance gates

| Gate | Requirement | Result | Status |
| --- | ---: | ---: | --- |
| Paper nDCG@10 | ≥ 0.80 | 0.7455 | **Fail** |
| Paper direct MRR@10 | ≥ 0.70 | 1.0000 | Pass |
| Paper judged Recall@20 | ≥ 0.90 | 1.0000 | Pass |
| Evidence nDCG@10 | ≥ 0.45 | 0.6948 | Pass |
| Evidence direct MRR@10 | ≥ 0.45 | 0.8571 | Pass |
| Evidence judged Recall@20 | ≥ 0.60 | 0.7769 | Pass |
| Source-anchor Recall@10, micro | ≥ 0.25 | 0.7500 | Pass |
| Source-anchor Recall@50, micro | ≥ 0.35 | 0.7500 | Pass |
| Positive source families with a hit by 10 | ≥ 0.50 | 0.8571 (6/7) | Pass |
| Hard failure fraction | ≤ 0.01 | 0/20 | Pass |
| Reranker fallback fraction | ≤ 0.35 | 2/20 = 0.1000 | Pass |
| Warm p95 | ≤ 1,500 ms | 1,533.96 ms | **Fail** |
| Combined cold model load | ≤ 15,000 ms | 5,303.73 ms | Pass |
| Summed CUDA allocated model memory | ≤ 1 GiB | 224,966,656 bytes | Pass |

The seven required evidence groups had 0.75 piece coverage and 0.5714 complete-group fraction at both result cutoffs. Group coverage is descriptive; no numeric threshold was predeclared.

The selected profile had zero hard primary failures and zero warm-repeat failures. All 20 primary quality requests were marked degraded with warnings and truncated results at the frozen 50-result limit. The run retained these responses for top-50 quality scoring and reported the degraded count separately. Result order was unchanged across all 100 warm repeats. The unsupported-query cutoff was disabled.

## Runtime, storage and replay

- Device: NVIDIA GeForce RTX 3050 Laptop GPU; CUDA available.
- Runtime startup: 8,044 ms. E5 model load: 4,968.5 ms; MiniLM reranker load: 335.2 ms; combined model load: 5,303.7 ms.
- Summed model allocation delta: 224,966,656 bytes; combined CUDA peak allocated: 275,554,816 bytes; peak reserved: 316,669,952 bytes.
- Process peak RSS: 1,718,554,624 bytes.
- BM25 and Hybrid E5 lexical artifacts: 38,737,423 bytes each. Fixed-window local profile artifacts: 28,179,129 bytes. Qdrant dense collection disk use was not isolated.
- Warm timing used five repeats over ten families, two search operations and 100 samples per profile, with result limit 10. Quality used the frozen result limit of 50.

The full private retrieval record is mode `0600` at `local-reference/phase2-runs/benchmark-v4/heldout-run-20260928T000648Z.json` (SHA-256 `6a208d0bc09502af6d0f25a1fe6085072fe1c7bf932949fea9a5df0951d10bb0`). The rank-free corrected aggregate is mode `0600` at `local-reference/phase2-runs/benchmark-v4/heldout-score-replay-v4-coverage-corrected.json` (SHA-256 `791aaa2881d7e9981c0a5f9bc03d2ca3da37ca8bfad7a3da8eb5676378e8f205`). Per-family hits, questions, titles, passages and ranks remain private.

With local evaluation services and cached offline models running, the retrieval replay command is:

```bash
/home/avsngh/miniconda3/envs/sci_research_agent/bin/python \
  local-reference/phase2-runs/benchmark-v4/run-heldout-evaluation-v4.py
```

The coverage-only scorer reuses the saved rankings and original timing sample:

```bash
/home/avsngh/miniconda3/envs/sci_research_agent/bin/python \
  local-reference/phase2-runs/benchmark-v4/rescore-paper-coverage-v4.py
```

No `*origins.json` file was read. The accepted Phase 1 snapshot/index was not modified. The earlier v3 aggregate assessment is archived in [phase-2-acceptance-report-v3.md](phase-2-acceptance-report-v3.md).

## Next phase boundary

P2-01–P2-19 implementation and hosted CI are complete. The v4 evaluation and coverage correction are recorded, but the frozen gate failed. Use development data for any system changes, then build and freeze a new held-out set before reassessment. The v4 questions and results cannot be reused for tuning or represented as unseen data. Phase 3 remains unstarted.
