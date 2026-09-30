# Phase 2: Is there published backing for absolute retrieval thresholds?

Status: assistant-reviewed. Web fetch could not extract tables from PDFs, so numbers marked
[UNVERIFIED] come from recall of the cited papers and must be checked before being quoted in an ADR.

## Summary

The IR literature judges systems relative to baselines (BM25, prior systems) on the same
test collection, with paired significance tests. I found no primary-source guidance that
says "nDCG@10 >= X is good enough". nDCG@10 is not comparable across collections because it
depends on topic difficulty, judgment depth, relevance-grade scale and corpus size. Absolute
thresholds are therefore project-local conventions. They are defensible only if framed as
regression guards or product targets calibrated on your own data and baselines.

## 1. Benchmark ranges (nDCG@10)

| Benchmark | BM25 | Strong dense / late-interaction | BM25 + cross-encoder | Source |
|---|---|---|---|---|
| TREC-COVID | ~0.656 | ColBERT ~0.677, TAS-B ~0.481, ANCE ~0.654 | ~0.757 | BEIR, https://arxiv.org/abs/2104.08663 [UNVERIFIED values] |
| NFCorpus | ~0.325 | ColBERT ~0.305, TAS-B ~0.319 | ~0.350 | BEIR [UNVERIFIED values] |
| SCIDOCS | ~0.158 | ColBERT ~0.145, TAS-B ~0.149 | ~0.166 | BEIR [UNVERIFIED values] |
| SciFact | ~0.665 | ColBERT ~0.671, TAS-B ~0.643 | ~0.688 | BEIR [UNVERIFIED values] |
| MTEB retrieval (modern embedders, same four sets) | n/a | SciFact roughly 0.70-0.80, SCIDOCS roughly 0.20-0.25, NFCorpus roughly 0.35-0.42 | n/a | https://arxiv.org/abs/2210.07316 and leaderboard https://huggingface.co/spaces/mteb/leaderboard [UNVERIFIED ranges] |
| LitSearch (597 literature queries) | recall@5 about 25 points below best dense retriever (abstract); LLM reranking adds about 4.4 points over best dense | see left | see left | https://arxiv.org/abs/2407.18940 (abstract verified; metric is recall@k, not nDCG) |

Take-aways for our numbers (paper nDCG@10 0.70-0.76, passage 0.41-0.52 on our dev set):
- Scores are in the range of published SciFact/TREC-COVID results for good systems, well above
  SCIDOCS/NFCorpus. That says nothing about "good enough", because our dev set differs in
  corpus, query style and judgment depth.
- BEIR spread across datasets for one system (0.15 to 0.75) shows the metric is dominated by the collection.
- BEIR's own headline finding (verified in abstract): BM25 is a robust baseline; reranking and late
  interaction do best on average. The benchmark is comparative.

## 2. Absolute "good enough" thresholds

- RAGAS (https://arxiv.org/abs/2309.15217) and ARES (https://arxiv.org/abs/2311.09476) define
  metrics (context precision/recall, relevance) and compare systems. ARES reports confidence
  intervals via prediction-powered inference. Neither proposes pass/fail cutoffs [UNVERIFIED by full read].
- TREC overviews (https://trec.nist.gov/) report per-run scores and significance, not acceptance levels.
- Sakai argues effect size and significance relative to a baseline are what matter:
  "On the reliability of IR evaluation and significance testing" line of work, see
  https://dl.acm.org/doi/10.1145/2911451.2911492 [UNVERIFIED exact title].
- Industry blogs (vendor RAG guides) sometimes quote targets such as "recall@k > 0.8". These are
  unsourced heuristics; I found no primary backing. [UNVERIFIED, not cited]

## 3. Significance and incomplete judgments

- Smucker, Allan, Carterette (CIKM 2007), "A comparison of statistical significance tests for IR
  evaluation": paired randomization / bootstrap / t-test agree; sign and Wilcoxon are less
  reliable. https://dl.acm.org/doi/10.1145/1321440.1321528 [UNVERIFIED URL id]
- Sakai (SIGIR 2016) "Statistical reform in IR?" and Carterette (2012) "Multiple testing in
  statistical analysis of systems-based IR experiments": report effect sizes and CIs, correct for
  multiple comparisons.
- Buckley and Voorhees (SIGIR 2004), "Retrieval evaluation with incomplete information": nDCG/MAP
  computed treating unjudged as non-relevant are biased against systems that did not contribute to
  the pool; bpref and condensed lists are more robust. https://dl.acm.org/doi/10.1145/1008992.1009000
  [UNVERIFIED URL id]
- Sakai and Kando (2008), "On information retrieval metrics designed for evaluation with
  incomplete relevance assessments": condensed-list nDCG/AP are robust. [UNVERIFIED]
- Yilmaz and Aslam (CIKM 2006), infAP: sampling-based estimator for incomplete judgments. [UNVERIFIED]
- Implication: if the dev set labels come from one system's pool, absolute nDCG is biased;
  compare variants on identical labels, and report the unjudged fraction at k.

## 4. How many queries

- Voorhees and Buckley (SIGIR 2002), "The effect of topic set size on retrieval experiment error":
  about 50 topics is a practical minimum; with 25 topics a difference of 0.05-0.10 MAP-like
  absolute may still be unreliable. https://dl.acm.org/doi/10.1145/564376.564432 [UNVERIFIED numbers]
- Sakai (2014+), topic set size design via power analysis: choose n from desired power, alpha, and
  score variance (often 50-100+ for small effects). https://waseda.box.com/ir4ir [UNVERIFIED URL]
- Zobel (1998) and Sanderson and Zobel (SIGIR 2005): significance plus reasonable effect size
  matters more than raw percent difference. [UNVERIFIED]
- Practical: per-query nDCG SD is typically 0.2-0.3, so with n=50 a paired difference of about 0.05-0.08
  is near the detectable limit; compute from our own per-query variance.

## Verdict

Absolute thresholds are NOT backed by the literature. Recommended framing for the ADR:
1. Gate on relative improvement over a fixed baseline (BM25 and the current dense profile),
   using paired bootstrap/randomization with CIs on identical labels, and report effect size.
2. Keep absolute numbers only as project-local regression floors, explicitly labeled as
   calibrated on our dev set, not as externally validated.
3. Check that the query count supports the effect size we want to detect (power analysis from
   per-query variance); report unjudged rates at k.
