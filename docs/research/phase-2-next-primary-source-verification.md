# Phase 2 next-set primary-source verification

**Status:** assistant-reviewed source verification; no questions, labels, or split assignments created

**Date:** 2026-09-29
**Scope:** the seven papers already listed in [the next-set source screen](phase-2-next-source-screening.md)

## Method and limits

I checked the result claims and anchors in the screen against the official ACL Anthology records/PDFs for six papers and the University of Amsterdam's UvA-DARE record plus its final-published-version PDF for the CIKM paper. The ACM DOI page for that paper returned HTTP 403, so its results below are checked against the repository copy that UvA identifies as the final published version. The repository record gives the proceedings pages, DOI, and version status.

PDF page numbers below are 1-based physical pages. Printed proceedings or journal pagination is shown separately. This distinction matters for the UvA PDF, which begins with a repository cover sheet. I recorded the evaluation unit, named metrics, evaluation split or collection, and reported uncertainty where the paper provides it. These are source studies and benchmark results, not measurements on this project's corpus. Their scores should not be compared numerically across papers unless the tasks and metrics match.

This follow-up uses only the seven listed primary papers. It does not inspect question items, judgments, candidate pools, ranking outputs, origins files, or prior held-out material. It drafts no questions and makes no family or split assignments. Novelty relative to prior held-out families remains uncertifiable because their identities are unavailable.

## Verified source results

### 1. COIL — retrieval effectiveness and latency

**Primary source:** [ACL Anthology record](https://aclanthology.org/2021.naacl-main.241/) · [official PDF](https://aclanthology.org/2021.naacl-main.241.pdf)

**Screen anchor check:** Confirmed. §5.1 Tables 1–2 are on printed p. 3036 (PDF p. 7); §5.2 Table 3 is on printed p. 3037 (PDF p. 8). Table 1 is MS MARCO passage ranking; Table 2 is MS MARCO document ranking. Both list reranking and retrieval metrics: MRR@10, Recall@1K, NDCG@10, and MRR@1K, with two distinct MRR@10 columns for development reranking and development retrieval. Table 3 reports development retrieval and TREC DL 2019 retrieval beside CPU/GPU latency in milliseconds.

The passage retrieval values support the screen's positive-but-scoped summary: COIL-tok has dev retrieval MRR@10 0.341 versus BM25 0.184; COIL-full is 0.355. For the document collection, COIL-tok is 0.385 and COIL-full 0.397 versus BM25 0.230. The paper attributes COIL-full's added benefit to its CLS match, which supplies a semantic signal alongside exact token matches. These are collection-specific retrieval/reranking results, not general evidence that all dense or lexical systems behave similarly.

**Conditions and uncertainty:** Table 3's speed test is on the passage collection; do not infer document-collection latency from Table 2. The caption says ColBERT uses approximate search and quantization and excludes I/O time. The tables provide no confidence intervals or repeat-count uncertainty. The paper describes some effectiveness comparisons as statistically significant, but the cited tables do not give intervals. See [§5.1, Tables 1–2, pp. 3035–3036](https://aclanthology.org/2021.naacl-main.241.pdf#page=7) and [§5.2, Table 3, p. 3037](https://aclanthology.org/2021.naacl-main.241.pdf#page=8).

### 2. MORES — reranking quality, timing, and storage

**Primary source:** [ACL Anthology record](https://aclanthology.org/2020.emnlp-main.342/) · [official PDF](https://aclanthology.org/2020.emnlp-main.342.pdf)

**Screen anchor check:** Confirmed. §4.2 discusses ranking effectiveness on printed pp. 4184–4185; Table 2 is on p. 4185 (PDF p. 6). §4.3 and Table 4 are on printed p. 4185 (PDF p. 6). Table 2 reports MRR for MS MARCO development queries and MRR, NDCG@10, and MAP for TREC 2019 Deep Learning queries. MORES 1× interaction block reaches about 95% of BERT-ranker performance; MORES 2× IB is reported as comparable under the paper's 2% non-inferiority margin. Three blocks did not improve accuracy, and four lowered some measures.

Table 4 reports average seconds to rank one query over 1,000 candidates. The fixed query length is 16; document lengths are 128 and 512; measurements use an 8-core CPU and one GPU. It compares two document-representation reuse strategies and reports per-document representation space. Speedups and space vary substantially by strategy and document length: the table reports CPU speedups from 20× to 170× and GPU speedups from 22× to 158× for the listed MORES rows, with 0.4–12 MB of representation space per document. This confirms a quality/speed/storage trade-off, with results conditional on this ranking setup and hardware.

**Conditions and uncertainty:** Table 2's asterisks and daggers denote non-inferiority to the BERT ranker at p < 0.05 with 5% and 2% margins, respectively; these are not confidence intervals. Table 4 reports averages but no repeat count, dispersion, or tail latency in the table. See [§4.2, Table 2, pp. 4184–4185](https://aclanthology.org/2020.emnlp-main.342.pdf#page=6) and [§4.3, Table 4, p. 4185](https://aclanthology.org/2020.emnlp-main.342.pdf#page=6).

### 3. Synthetic-document training data — cross-encoder reranking

**Primary source:** [UvA-DARE record](https://dare.uva.nl/id/a3aac532-b09e-40b0-9074-9ae8be2fb4c5) · [final-published-version PDF](https://pure.uva.nl/ws/files/169472407/3583780.3615111.pdf) · [DOI](https://doi.org/10.1145/3583780.3615111). The UvA record identifies the PDF as the final published version and gives CIKM ’23 proceedings pp. 5311–5315. The direct [ACM page](https://dl.acm.org/doi/10.1145/3583780.3615111) could not be fetched (HTTP 403).

**Screen anchor check:** Confirmed. §4.1 Table 2 is on printed p. 5313 (PDF p. 4, counting the UvA cover); §4.2 Table 3 is on printed p. 5314 (PDF p. 5). The metrics are MAP@1000, NDCG@10, and MRR@10. Table 2 compares MiniLM/TinyBERT cross-encoders trained on human or ChatGPT responses: inference ranks human responses, in-domain on ChatGPT-RetrievalQA and out-of-domain on TREC DL ’19/’20 and MS MARCO Dev. The in-domain aggregate favors human-trained MiniLM (.310/.384/.460 versus .294/.362/.444); ChatGPT-trained MiniLM wins across all three metrics on TREC DL ’20 and MS MARCO Dev. On TREC DL ’19, the best model varies by metric, so the appropriate claim is mixed and collection-dependent. Table 3 breaks in-domain results down by domain; the aggregate favors human-trained MiniLM, with mixed comparisons in the Wikipedia-domain subsets.

**Conditions and uncertainty:** Re-ranking depth is 1,000. Table 2 marks statistically significant comparisons using paired t-tests with p < 0.05 and Bonferroni correction; cutoffs are 1,000/10/10 for MAP/NDCG/MRR. The paper notes potential train/test document overlap for the human-trained in-domain setup. Table 3 does not report confidence intervals. The screen's “helps on some out-of-domain collections” summary is supported; do not generalize it to every dataset or metric. See [§4.1, Table 2, p. 5313](https://pure.uva.nl/ws/files/169472407/3583780.3615111.pdf#page=4) and [§4.2, Table 3, p. 5314](https://pure.uva.nl/ws/files/169472407/3583780.3615111.pdf#page=5).

### 4. IIRC — context insufficiency and end-to-end QA

**Primary source:** [ACL Anthology record](https://aclanthology.org/2020.emnlp-main.86/) · [official PDF](https://aclanthology.org/2020.emnlp-main.86.pdf)

**Screen anchor check:** Confirmed. §2.4 Table 1 is on printed p. 1140 (PDF p. 4); §4.3 Table 3 is on p. 1143 (PDF p. 7). Table 1's task-type percentages were computed from a manual analysis of 100 examples. Its “None” category means that the question cannot be answered from the provided context; the table reports 30% in that analyzed sample. It does not mean the answer is absent from every linked source or from this project's snapshot.

Table 3 reports exact match (EM) and F1 for the full model, oracle-link/context conditions, and human assessment. On the test set, the full model scores 27.7 EM / 31.1 F1. Human assessment is 85.7 / 88.4 on a 200-example test subset. This is a multi-context reading-comprehension/answering task; the result is not a paper- or passage-retrieval score.

**Conditions and uncertainty:** The human score has a stated 200-example subset; no confidence interval is shown in the cited table. Table 1's percentages have the 100-example manual-analysis denominator, not the entire IIRC dataset. See [§2.4, Table 1, p. 1140](https://aclanthology.org/2020.emnlp-main.86.pdf#page=4) and [§4.3, Table 3, p. 1143](https://aclanthology.org/2020.emnlp-main.86.pdf#page=7).

### 5. ColBERT-QA — retrieval success and downstream answer extraction

**Primary source:** [ACL Anthology record](https://aclanthology.org/2021.tacl-1.55/) · [official PDF](https://aclanthology.org/2021.tacl-1.55.pdf)

**Screen anchor check:** Confirmed. §4.3 Table 1 is on journal p. 936 (PDF p. 8); §4.4 Table 2 is on p. 937 (PDF p. 9). Table 1 includes test-set Success@20 values and separate development-set EM values. Table 2 is explicitly test-set retrieval quality: Success@k for k = 1, 5, 10, 20, 50, 100, and MRR@100, comparing ColBERT-QA3 with its gains over QA1 on Natural Questions, TriviaQA, and SQuAD.

The screen's retrieval claim is supported: Table 2 reports positive QA3-minus-QA1 gains at all listed depths. At Success@20, the gains are +2.3, +0.9, and +1.6 points for NQ, TriviaQA, and SQuAD; the largest listed gain is +5.7 at Success@1 on NQ. Retrieval Success@k measures whether an answer occurs in the retrieved passages. Downstream reader EM is a different outcome; the paper states that higher Success@k does not always imply higher EM with a particular reader.

**Conditions and uncertainty:** The authors report Wilcoxon signed-rank tests with p < 0.05 and Bonferroni correction showing QA2 and QA3 significantly above QA1 on Success@20; they detect no significant QA2–QA3 difference. This test is stated for Success@20, so do not describe every tabled Success@k difference as independently significant. See [§4.3, Table 1, p. 936](https://aclanthology.org/2021.tacl-1.55.pdf#page=8) and [§4.4, Table 2, p. 937](https://aclanthology.org/2021.tacl-1.55.pdf#page=9).

### 6. DiPair — product/query-to-passage pair scoring

**Primary source:** [ACL Anthology record](https://aclanthology.org/2020.findings-emnlp.264/) · [official PDF](https://aclanthology.org/2020.findings-emnlp.264.pdf)

**Screen anchor check:** Confirmed. §4.5 Tables 2–3 and §4.6 Table 4 are on printed p. 2932 (PDF p. 8). Table 2 evaluates P2T-REL product-to-term relevance using Pearson correlation and Delta against the BERT-base teacher. Table 3 evaluates Q2P-MAT query-to-passage matching with AUC-ROC and Delta. On Q2P-MAT test, DiPairTSF reports AUC-ROC .932 at 355× teacher speedup; BERT-Tiny reports .936 at 44×. The paper describes this as similar quality with an 8× speedup over BERT-Tiny. The simplest cosine dual encoder is fastest among the listed students but has lower quality. Table 4 varies head settings and reports AUC-ROC, parameter count, and speedup.

**Conditions and uncertainty:** These are pair-matching/regression or binary-classification tasks, not first-stage full-corpus retrieval. The speedup calculation is based on CPU timing for the model heads (the paper gives its pair/product/term timing formula), not an end-to-end search-service latency. Q2P-MAT uses a teacher input length of 128 and query/passage encoder lengths of 32/128 for the reported table. Asterisks denote p < 0.05 versus the closest baseline; no confidence intervals or timing dispersion are shown. See [§4.5, Tables 2–3, p. 2932](https://aclanthology.org/2020.findings-emnlp.264.pdf#page=8) and [§4.6, Table 4, p. 2932](https://aclanthology.org/2020.findings-emnlp.264.pdf#page=8).

### 7. DensePhrases — phrase retrieval, answer accuracy, and resources

**Primary source:** [ACL Anthology record](https://aclanthology.org/2021.acl-long.518/) · [official PDF](https://aclanthology.org/2021.acl-long.518.pdf)

**Screen anchor check:** The reported outcomes are supported, with one location correction. Table 1 is on printed p. 6635 (PDF p. 2) in the introductory material, outside §7.2. §7.2 Tables 2 and 3 are on printed pp. 6640–6641 (PDF pp. 7–8). Thus “§7.2, Tables 1–3” should be refined to “Table 1, p. 6635; §7.2, Tables 2–3, pp. 6640–6641.”

Table 1 compares open-domain QA retriever-reader and phrase-retrieval approaches. It includes storage, questions per second on GPU/CPU, and Natural Questions/SQuAD test accuracy. DensePhrases is listed with 320 GB storage, 20.6/13.6 questions per second, and 40.9/38.0 accuracy; the comparison is against systems with different architectures and resource profiles. Appendix A reports about 20 hours to index the full phrase representations using four 24-GB GPUs. Table 2 reports reading-comprehension EM/F1 on SQuAD and long-answer Natural Questions development sets. Table 3 reports open-domain QA exact match on test sets across NQ, WebQuestions, TREC, TriviaQA, and SQuAD, with separate phrase-index training-data settings. The improvement over earlier phrase-retrieval systems is substantial on most listed datasets but not SQuAD; these are answer-task results, not passage-ranking nDCG or evidence-recall measurements.

**Conditions and uncertainty:** Table 2 marks some comparator results as estimates from figures in the original papers. Table 3 distinguishes zero-shot comparisons and extra pretraining in its footnotes. The cited tables report point values without confidence intervals. The screen's storage and QA summary is supported; keep answer EM/F1, resource throughput, and ranking metrics distinct. See [Table 1, p. 6635](https://aclanthology.org/2021.acl-long.518.pdf#page=2), [§7.2, Table 2, p. 6640](https://aclanthology.org/2021.acl-long.518.pdf#page=7), [§7.2, Table 3, p. 6641](https://aclanthology.org/2021.acl-long.518.pdf#page=8), and [Appendix A, p. 6646](https://aclanthology.org/2021.acl-long.518.pdf#page=13).

## Discrepancies and carry-forward wording

- **Location correction:** DensePhrases Table 1 is not in §7.2. Tables 2–3 are.
- **Metric boundaries:** IIRC's “None” is only relative to its provided context; DiPair is pair scoring; DensePhrases and the reader-side ColBERT/IIRC results include answer-task measures. None of those should be relabeled as this project's retrieval metric.
- **Scope of comparative claims:** COIL latency is tied to its reported passage setup; MORES averages are tied to 1,000-candidate ranking and the listed hardware; synthetic-training results vary by collection and metric; ColBERT's formal significance test is reported for Success@20; DiPair speedups are head-timing ratios.
- **Uncertainty:** The papers do not offer a common uncertainty format. Preserve the stated tests and denominators above; where intervals, repeat counts, or significance tests are absent, treat the table values as reported point estimates rather than new claims of statistical reliability.

## Sources checked

- COIL, official ACL Anthology PDF and record: [record](https://aclanthology.org/2021.naacl-main.241/), [PDF](https://aclanthology.org/2021.naacl-main.241.pdf).
- MORES, official ACL Anthology PDF and record: [record](https://aclanthology.org/2020.emnlp-main.342/), [PDF](https://aclanthology.org/2020.emnlp-main.342.pdf).
- Synthetic-document rankers, UvA-DARE final published version and record: [record](https://dare.uva.nl/id/a3aac532-b09e-40b0-9074-9ae8be2fb4c5), [PDF](https://pure.uva.nl/ws/files/169472407/3583780.3615111.pdf), [DOI](https://doi.org/10.1145/3583780.3615111). The [ACM page](https://dl.acm.org/doi/10.1145/3583780.3615111) returned HTTP 403.
- IIRC, official ACL Anthology PDF and record: [record](https://aclanthology.org/2020.emnlp-main.86/), [PDF](https://aclanthology.org/2020.emnlp-main.86.pdf).
- ColBERT-QA, official ACL Anthology PDF and record: [record](https://aclanthology.org/2021.tacl-1.55/), [PDF](https://aclanthology.org/2021.tacl-1.55.pdf).
- DiPair, official ACL Anthology PDF and record: [record](https://aclanthology.org/2020.findings-emnlp.264/), [PDF](https://aclanthology.org/2020.findings-emnlp.264.pdf).
- DensePhrases, official ACL Anthology PDF and record: [record](https://aclanthology.org/2021.acl-long.518/), [PDF](https://aclanthology.org/2021.acl-long.518.pdf).
