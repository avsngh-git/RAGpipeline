# P2-12.3 replacement held-out question source audit: q31

**Reviewer:** assistant · **Date:** 2026-09-27 · **Status:** source checked and frozen before q31 retrieval; retained unchanged in the active v3 query manifest.

## Frozen family

- **Family:** q31, replacement for excluded q21
- **Categories:** discovery, specific evidence, filters
- **Snapshot filter:** publication year 2024
- **Question:** “In a 2024 long-context RAG study, what attention pattern do the authors identify in lost-in-the-middle cases, and how does their calibration approach handle relevant context placed in the middle of the input?”
- **Original freeze:** `benchmarks/phase2/benchmark-heldout-questions-v2.toml`; its hash was bound by split v2. The active v3 manifest retains q31 and is bound by `benchmarks/phase2/benchmark-split-v3.toml`.

## Source check

The source is *Found in the middle: Calibrating Positional Attention Bias Improves Long Context Utilization* (paper ID `W4402684028`), included in accepted snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c`. The accepted PDF SHA-256 is `d18854e7dcf46489fe7708e15151a1608f523f23f083175787875ad6a7a3038e`. The abstract on PDF page index 0 directly supports both requested pieces: it identifies an attention bias that favors the beginning and end of the input irrespective of relevance, and describes calibration that lets the model attend to relevant context faithfully when it appears in the middle.

The accepted extraction's abstract chunk and the fixed-window variant's multi-span chunk were matched to the same PDF and abstract text. The query asks for the reported mechanism, not the paper's comparative result, so no score or outcome claim is required to answer it.

Primary source: [ACL Anthology paper](https://aclanthology.org/2024.findings-acl.890/) · [official ACL PDF](https://aclanthology.org/2024.findings-acl.890.pdf).

## Replacement rationale

q21 is excluded because its private held-out ranks and scores were accidentally exposed during reviewer-card sampling. q31 was selected from the accepted snapshot's paper catalog, source checked against the accepted PDF, and frozen before q31 retrieval. Its category set preserves the discovery, specific-evidence, and filter coverage contributed by q21. The active v3 held-out split has ten eligible families, q22–q31. No held-out scores are used for tuning.
