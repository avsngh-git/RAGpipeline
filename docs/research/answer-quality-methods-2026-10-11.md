# Methods to raise answer quality: literature review

**Status:** assistant-researched, 2026-10-11. Research note only: it changes no phase gate,
ADR or acceptance. Any change it suggests goes through the source-of-truth change-control
process before it is built.

**Scope:** published, evidence-backed methods that could raise answer quality in our
scientific-literature RAG pipeline: evidence selection, decomposition, attribution,
abstention, model choice and training under 4 GiB VRAM, structured output and thinking,
tables, and evaluation. Any architectural change was in scope. No question, claim, answer
or passage text appears here.

**Method:** primary sources only (arXiv abstract and HTML pages, ACL/ICLR/NeurIPS/EMNLP
versions, official model cards and repositories). Figures were read from those pages
with an automated page reader, not retyped from PDFs. Each figure is labelled:

- **Measured** — reported by the cited source for the setting given.
- **Inference** — the assistant's reasoning about our pipeline. No source measured it.
- **Unconfirmed** — read from a figure or a long table and not cross-checked. Check the
  source before quoting the number.

## Our starting point

These are the diagnostics in the request, summarized from the
[Phase 3 diagnosis](phase-3-answer-quality-diagnosis.md) and later sweeps:

- Last 42-run sweep: 5 `answered`, 25 `partially_supported`, 12 `insufficient_evidence`;
  mean 1.5 kept claims; answers cover about 23% of reviewed facets.
- 57 of 131 synthesis calls declared insufficient evidence, although a source review
  found none of 69 contexts insufficient.
- Thinking groups passages into guessed handle ranges instead of reading each one.
  There are about 33 self-reversals per synthesis thought.
- Many drafted claims fail verification: the quote is not verbatim, or numbers are
  stitched together from different table cells.
- Prompt-only fixes did not reduce abstention in replays.

The generator is Qwen3.5-2B (Q4_K_M, Ollama, thinking on). It shares a 4 GiB GPU with
the retrieval models and already uses the model card's recommended thinking sampling
(`temperature` 1.0, `top_k` 20, `presence_penalty` 1.5, in
`src/research_platform/config.py`).

## Recommendations, ranked

The ranking is by expected gain for our setup. It is assistant inference built on the
measured evidence cited for each item. Items 1–3 change how the 2B model is asked to
work. Items 4–6 change what it sees or which model does the work.

### 1. Split synthesis into per-passage extraction, then synthesis over extracts

- **Change:** before synthesis, make one small call per passage, or per paper with at
  most 3 passages. The call asks: "Which sentences of this passage state facts that
  answer the question, or one of its facets?" It returns sentence IDs, or none. The final
  synthesis then sees only the extracted sentences, grouped by paper, and writes claims
  over them. This replaces "read 26–29 passages at once and pick quotes".
- **Evidence (measured):**
  - Attribute First, then Generate: the pipeline selects source spans, plans the
    sentences, then generates. On long-form QA it reached AutoAIS 89.3 against 49.8 for
    the ALCE baseline, with citations 45 times shorter, and halved human verification
    time (35 s against 59 s)
    ([Slobodkin et al., ACL 2024](https://arxiv.org/html/2403.17104)). Models: Gemini
    (in-context) and fine-tuned PRIMERA.
  - FRONT extracts quotes first, then generates anchored to them: +14.21% average
    citation quality with LLaMA-2-7B, above ChatGPT
    ([Huang et al., ACL Findings 2024](https://arxiv.org/abs/2408.04568)).
  - Ai2 Scholar QA runs per-paper verbatim quote extraction, then plans sections, then
    writes each section from its assigned quotes. It led ScholarQA-CS with 61.9, against
    53.5 for OpenScholar (GPT-4o) and 51.4 for PaperQA2. The paper gives no component
    ablation ([Singh et al., ACL 2025 demo](https://arxiv.org/html/2504.10861)).
  - Chain-of-Note writes a reading note for each document before answering: +7.9 EM with
    fully noisy documents, LLaMA-2-7B fine-tuned
    ([Yu et al., EMNLP 2024](https://arxiv.org/abs/2311.09210)).
- **Why it fits (inference):** it removes the skimming failure, because each call has
  one passage to read. It also cuts each call's context from about 4K tokens to a few
  hundred. Small models use long contexts worst (see area 5).
- **Cost:** 26–40 short calls per question. They can run without thinking or with short
  thinking (see item 3). Latency is likely similar to or above today's 2–7 min synthesis;
  it must be measured.
- **Risk:** PaperQA2 found that weaker models doing relevance scoring plus summarization
  in its RCS step *lowered* accuracy: "smaller models (GPT-3.5-Turbo (RCS), Llama3
  (70B)) decrease overall accuracy … relative to not using a model at all"
  ([Skarlinski et al. 2024](https://arxiv.org/html/2409.13740)). So keep the 2B's task
  extractive (select sentence IDs, yes/no), not abstractive (summarize, score 0–10).
  EXIT shows a 2B model can do sentence selection, but EXIT is fine-tuned (item 6).

### 2. Cite sentence IDs instead of copying quotes

- **Change:** number the sentences in every passage (`P12.s3`) and the rows in every
  table (`T4.r7`). Claims cite IDs. Code builds the quote from the IDs, so a quote is
  verbatim by construction. Keep the existing number, scope and row checks, run against
  the assembled text.
- **Evidence (measured):**
  - LongCite splits context into NLTK sentences and cites `[k]` or `[a-b]`. LongCite-8B
    beat GPT-4o on citation F1 by 6.4%, with citations of about 85 tokens against 220
    ([Zhang et al. 2024](https://arxiv.org/html/2409.02897)). SFT on cited data also
    "consistently improves response correctness".
  - EXIT casts compression as yes/no sentence classification with Gemma-2B. With a
    Llama-3.1-8B reader it gained over the uncompressed context (2Wiki 24.2 against 16.1
    EM, HotpotQA 30.6 against 28.1) at 0.8 s latency
    ([Hwang et al., ACL Findings 2025](https://arxiv.org/html/2412.12559)).
- **Why it fits (inference):** "quote not verbatim" is a copying failure, and thinking
  makes exact copying worse (item 3). Selecting a short ID removes that failure mode.
- **Cost:** low. It changes the evidence formatter, the output schema and the
  verifier's quote lookup.
- **Risk:** the model may cite the wrong sentence ID. The overlap and number checks still
  catch claims that do not match their sentences.

### 3. Match the thinking mode to each sub-task, and measure loops

- **Change:** keep thinking for planning-type steps: facet planning and final synthesis
  over a few extracts. Test non-thinking mode for exact-form steps: per-passage sentence
  selection and table-row extraction. This respects the owner's rule against cutting
  thinking budgets. It does not cap thinking; it routes each step to the mode that
  measures better. Log loop and repetition counts per call.
- **Evidence (measured):**
  - The Qwen3.5-2B card: "Qwen3.5-2B is more prone to entering thinking loops compared to
    other Qwen3.5 models, which may prevent it from terminating generation properly",
    under the recommended sampling we already use
    ([model card](https://huggingface.co/Qwen/Qwen3.5-2B)).
  - Across reasoning-model families, "within each family larger models loop less", and
    looping is worst at low temperature
    ([Wait, Wait, Wait…, 2025](https://arxiv.org/html/2512.12895v1)).
  - On Qwen3 1.7B–32B, built-in thinking improves "planning" constraints but
    "consistently worsens" "precision" constraints of exact local form. 10–20% of prompts
    flip between modes ([Senthil Kumar, 2026](https://arxiv.org/abs/2606.09662)).
- **Why it fits (inference):** the 33 self-reversals per thought and the guessed handle
  ranges look like the loop behaviour the card describes. Verbatim quoting is a
  precision constraint.
- **Cost:** a config switch per call type, plus a replay comparison.
- **Risk:** the instruction-following study is not a RAG study. The effect must be
  measured on our replays before adoption.

### 4. Use a larger generator for synthesis by freeing the GPU after retrieval

- **Change:** retrieval is finished when synthesis starts. Unload or move the retrieval
  models (about 1.9 GiB) to CPU for the synthesis call, then run Qwen3.5-4B at Q4_K_M or
  IQ4_XS on the GPU. A fallback is partial CPU offload of the 4B. Also try the 4B only
  for the final synthesis, with the 2B for extraction calls.
- **Evidence:**
  - Measured, from the 2B card's language table: Qwen3.5-2B scores MMLU-Redux 69.2,
    IFEval 61.2, AA-LCR 25.6 and LongBench v2 38.7. Qwen3-4B-2507 scores 84.2, 83.4, 32.0
    and 42.8 ([Qwen3.5-2B card](https://huggingface.co/Qwen/Qwen3.5-2B)). The
    Qwen3.5-4B card lists MMLU-Redux 88.8, IFEval 89.8, AA-LCR 57.0 and LongBench v2 50.0
    ([Qwen3.5-4B card](https://huggingface.co/Qwen/Qwen3.5-4B)). Unconfirmed: whether
    those 4B rows are thinking or non-thinking, so the two cards may not be comparable.
  - Measured GGUF sizes for Qwen3.5-4B: Q4_K_M 3.01 GB, IQ4_XS 2.67 GB, Q3_K_M 2.58 GB
    ([bartowski GGUF](https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF)).
  - Measured: models of 7B and below "fail to extract the correct answer 85 to 100
    percent of the time" from oracle passages on questions beyond their knowledge.
    The dominant failure is ignoring the context. The study covers SmolLM2, Qwen2.5 and
    Llama 3.1, from 360M to 8B ([Pandey et al. 2026](https://arxiv.org/abs/2603.11513)).
  - Measured: PaperQA2 reports a "comprehension threshold" for evidence processing
    ([2409.13740](https://arxiv.org/html/2409.13740)).
- **Feasibility (inference):** 3.01 GB of weights plus KV cache and CUDA overhead is
  tight on 4 GiB. Only 1 in 4 Qwen3.5 layers is full attention (the rest are Gated
  DeltaNet, per the card), so KV cache should grow slowly with context. IQ4_XS gives
  headroom. Fit and speed are unverified and must be measured. CPU offload works in
  llama.cpp/Ollama but will be much slower; no source here measures it on our hardware.
- **Risk:** reloading models adds latency, though the owner prioritizes precision. The
  4B card does not repeat the 2B's loop warning, which suggests but does not prove fewer
  loops.

### 5. Decompose questions into facets; answer and decide sufficiency per facet

- **Change:** the planner already exists. Have it emit 2–5 facets with their retrieval
  queries. Retrieve and extract (item 1) per facet. Write at most 1–2 claims per facet.
  Allow "no retrieved paper reports X; [paper] reports Y" as a typed *facet gap* claim.
  Code checks facet coverage: every facet ends with a claim or an explicit gap.
- **Evidence (measured):**
  - IRCoT interleaves retrieval with chain-of-thought steps: retrieval up to +21 points
    and QA up to +15 points on four multi-hop datasets. It also works with Flan-T5-large
    ([Trivedi et al., ACL 2023](https://arxiv.org/abs/2212.10509)).
  - Self-ask: explicit follow-up sub-questions narrow the compositionality gap, and
    adding search to the sub-questions raises accuracy further
    ([Press et al., EMNLP Findings 2023](https://arxiv.org/abs/2210.03350)).
  - Least-to-most: 99% against 16% for chain-of-thought on SCAN
    ([Zhou et al., ICLR 2023](https://arxiv.org/abs/2205.10625)). Not a RAG setting.
  - IterDRAG decomposes queries into sub-queries with interleaved retrieval and scales
    better than one-shot DRAG at large budgets. Overall: "up to 58.9%" over standard RAG,
    Gemini 1.5 Flash
    ([Yue et al., ICLR 2025](https://arxiv.org/html/2410.04343)). Unconfirmed per-dataset
    figures.
  - Ai2 Scholar QA plans sections before writing and assigns quotes to each section
    ([2504.10861](https://arxiv.org/html/2504.10861)).
- **Why it fits (inference):** answers cover 23% of facets. A single synthesis call
  favours the most literal sub-clause. Per-facet calls force coverage and make abstention
  local.
- **Cost:** more calls, and more retrieval calls (GPU contention with item 4). Medium
  engineering.
- **Risk:** a 2B planner may produce poor facets. Validate them against our reviewed
  facets first.

### 6. Make `insufficient_evidence` a computed outcome, not the generator's flag

- **Change:** drop the generator's global `insufficient_evidence` flag, or demote it to a
  logged signal. The outcome becomes a code decision: no verified claim and no facet-gap
  claim means `insufficient_evidence`. If a sufficiency judgement is still wanted, use a
  separate per-facet check: list the sub-questions, answer each from the evidence, then
  label. Combine it with a confidence signal.
- **Evidence (measured):**
  - Sufficient Context: smaller models "hallucinate or abstain often, even with
    sufficient context". Selective generation, which combines a sufficiency label with
    self-rated confidence in a logistic regression, raised the correct fraction among
    answered by 2–10%. The autorater reached 93% accuracy by writing step-by-step
    sub-questions and answering each before labelling
    ([Joren et al., ICLR 2025](https://arxiv.org/html/2411.06037)).
  - The same paper: models answer correctly 35–62% of the time even when context is
    insufficient, so one global sufficient/insufficient flag is a poor proxy for
    "can answer something".
  - Trust-Score scores "excessive refusal" separately from over-responsiveness. Prompting
    alone left small models (0.5B–8B, including Qwen-2.5 and Phi-3.5) poorly calibrated;
    Trust-Align preference tuning fixed this in 26 of 27 models
    ([Song et al., ICLR 2025 oral](https://arxiv.org/abs/2409.11242)).
- **Why it fits (inference):** our source review found 0 of 69 contexts insufficient,
  yet the model declined in 57 of 131 calls. Prompt fixes failed, which matches the
  finding that prompting does not calibrate small-model refusal.
- **Cost:** low for the computed outcome. Medium for a separate sufficiency check.
- **Risk:** more unsupported claims reach verification. The verifier, and item 8, must
  carry the precision load.

### 7. Shrink and reorder the evidence pack before synthesis

- **Change:** after reranking, keep at most 3 passages per paper and about 10 passages in
  total for synthesis (or per facet). Prune sentences inside passages. Put the best
  passages at the start and end of the pack.
- **Evidence (measured):**
  - OpenScholar uses 5 passages for single-paper tasks and 10 for multi-paper tasks, at
    most 3 per paper. Removing reranking cut OS-8B citation F1 from 47.9 to 28.2
    ([Asai et al. 2024](https://arxiv.org/html/2411.14199)).
  - PaperQA2: 5 summaries in the answer gave the highest accuracy, 15 the highest
    precision. Accuracy rose with chunk depth from 1 to 10 ([2409.13740](https://arxiv.org/html/2409.13740)).
  - With a strong retriever, output quality first rises then falls as passage count
    grows, because of hard negatives. Reordering best-at-the-ends helps when passages are
    many (Gemma-7B, Gemma-2-9B, Mistral-Nemo-12B, Gemini-1.5-Pro)
    ([Jin et al., ICLR 2025](https://arxiv.org/html/2410.05983)).
  - U-shaped use of position: the middle of the context is used worst
    ([Liu et al., TACL 2024](https://arxiv.org/abs/2307.03172)).
  - Provence prunes sentences with "negligible to no drop in performance" and also
    reranks ([Chirkova et al., ICLR 2025](https://arxiv.org/abs/2501.16214)).
    `naver/provence-reranker-debertav3-v1` has 430M parameters, a 512-token input limit,
    is English-only, licensed CC BY-NC-ND 4.0, and trained on MS MARCO and NQ
    ([card](https://huggingface.co/naver/provence-reranker-debertav3-v1)).
- **Caution:** the Phase 3 diagnosis found that a 3,000-token pack made our model
  decline *more* often (14 against 8 runs). Shrinking alone is not enough; it should come
  with item 6 (the model no longer owns abstention) or item 1 (extraction first).
- **Cost:** low. Provence would be another GPU/CPU model; reranker scores already exist.
- **Risk:** Provence is trained on web QA, not scientific prose or tables. Its
  non-commercial licence must be acceptable.

### 8. Add a small NLI fact-checker as a second verifier

- **Change:** run MiniCheck-Flan-T5-Large (770M) or AlignScore (355M) on CPU for each
  claim against its cited sentences. Use it to accept faithful paraphrases that fail the
  50% content-word rule, and to reject claims that pass lexically but are not entailed.
  Keep the lexical number and scope-word checks as hard gates.
- **Evidence (measured):** on LLM-AggreFact, MiniCheck-FT5 scores 74.7 balanced accuracy
  against GPT-4's 75.3 and AlignScore's 70.4, at $0.24 against $107 for the 13K test set
  ([Tang et al., EMNLP 2024](https://arxiv.org/html/2404.10774)). The models are
  sentence-level: "MiniCheck(document, sentence) → [0, 1]"; split multi-sentence claims
  first ([repo](https://github.com/Liyan06/MiniCheck)). AlignScore "matches or even
  outperforms" ChatGPT/GPT-4-based metrics
  ([Zha et al., ACL 2023](https://arxiv.org/abs/2305.16739)). Bespoke-MiniCheck-7B is
  stronger but 7B and CC BY-NC
  ([card](https://huggingface.co/bespokelabs/Bespoke-MiniCheck-7B)).
- **Why it fits (inference):** a purpose-trained checker avoids the inconsistency
  the Phase 3 diagnosis found in the 2B LLM support judge. It may raise kept claims
  without losing precision.
- **Cost:** a 770M model on CPU is likely seconds per claim (unmeasured), with at most
  6 claims.
- **Risk:** about 25% balanced error on LLM-AggreFact. Treat it as an extra filter or a
  rescue path, never as the only gate for numbers.

### 9. Represent tables as one row per passage, with every cell labelled

- **Change:** serialize each table row as its own evidence unit, with the caption and
  column headers repeated on every cell: `Table 3 (caption) | row: <row label> |
  <column header>: <value>`. Rows get IDs (item 2). A numeric claim may cite one row
  only, unless code does the comparison. For "compare across papers" questions, code
  builds a small comparison from the cited rows, and the model only states it.
- **Evidence (measured):**
  - Input format, content order and partition marks change LLM table understanding. In
    one study HTML beat natural language with separators by 6.76%, and ordering choices
    plus self-augmented prompting added 0.84–5.68% on TabFact, HybridQA, SQA, FEVEROUS
    and ToTTo, with GPT-3.5/4
    ([Sui et al., WSDM 2024](https://arxiv.org/html/2305.13062)). Unconfirmed per-format
    accuracies.
  - Chain-of-Table: making table operations explicit intermediate steps gave
    state-of-the-art results on WikiTQ, FeTaQA and TabFact
    ([Wang et al., ICLR 2024](https://arxiv.org/abs/2401.04398)).
  - ChatRAG Bench includes table QA and arithmetic sub-tasks for RAG models
    ([Liu et al., NeurIPS 2024](https://arxiv.org/abs/2401.10225)).
- **Why it fits (inference):** stitched numbers come from cells far from their headers in
  wide pipe rows. Repeating headers per cell removes the alignment step that small models
  get wrong.
- **Cost:** low to medium, in the evidence formatter.
- **Risk:** longer table text. Mitigate by pruning to the cited rows.

### 10. Later: fine-tune for grounded, citing, calibrated answers (cloud, not local)

- **Change:** build training data with our pipeline and a large teacher, then LoRA-tune
  the 2B or 4B in the cloud. The data: question, evidence with distractors, sentence-ID
  claims, facet gaps, and correct refusals. Serve the merged GGUF locally.
- **Evidence (measured):**
  - RAFT trains with one golden and four distractor documents and chain-of-thought with
    verbatim quotes. 7B results: PubMed 73.30 against 58.8 for Llama2-7B+RAG; the quote
    CoT adds 9.66 points on HotpotQA
    ([Zhang et al. 2024](https://arxiv.org/html/2403.10131)).
  - OpenScholar-8B (Llama 3.1 8B, 130K synthetic instances from its own pipeline)
    reaches citation F1 47.9 on ScholarQA-CS. Llama3.1-8B with the same datastore reaches
    24.5. GPT-4o without retrieval reaches 0.1
    ([2411.14199](https://arxiv.org/html/2411.14199)).
  - InstructRAG: self-synthesized denoising rationales, +8.3% relative over the best
    baseline on average ([Wei et al., ICLR 2025](https://arxiv.org/abs/2406.13629)).
  - Trust-Align raised small-model Trust-Score, for example Qwen-2.5-0.5B from 22.83 to
    54.76 (unconfirmed table read) ([2409.11242](https://arxiv.org/abs/2409.11242)).
  - Pleias-RAG (350M and 1B) is trained to cite with literal quotes and reported as
    competitive with Qwen-2.5-7B, Llama-3.1-8B and Gemma-3-4B on HotPotQA and 2Wiki
    ([Langlais et al. 2025](https://arxiv.org/abs/2504.18225)).
- **Feasibility (measured, from the vendor):** Unsloth lists bf16 LoRA at 5 GB for
  Qwen3.5-2B and 10 GB for 4B. It states QLoRA "is not recommended" for Qwen3.5 because
  of large quantization differences, and offers free Colab notebooks for 0.8B, 2B and 4B
  ([Unsloth Qwen3.5 guide](https://unsloth.ai/docs/models/qwen3.5/fine-tune)). Its
  generic table puts a 3B QLoRA at 3.5 GB minimum
  ([requirements](https://unsloth.ai/docs/get-started/beginner-start-here/unsloth-requirements)).
  **Conclusion:** local fine-tuning of Qwen3.5 on a 4 GiB card is not feasible in the
  recommended setup. Cloud or Colab LoRA is. Keep at least 75% reasoning examples to
  preserve thinking (same Unsloth guide).
- **Risk:** the largest effort; needs a data pipeline and an evaluation set kept
  separate from training. Do it only after items 1–6 are measured.

## Area 1: evidence selection and compression

- **Per-chunk scoring and summarization (PaperQA2 RCS).** An LLM returns
  `{summary, relevance_score (integer out of 10)}` for each chunk and reranks by the
  score. With GPT-4-Turbo, removing RCS significantly lowered accuracy. With
  GPT-3.5-Turbo or Llama3-70B doing RCS, accuracy fell below no RCS at all. On LitQA2,
  precision is correct/answered and accuracy is correct/all; the main system scored 64.4%
  accuracy and 91.3% precision on 147 questions
  ([2409.13740](https://arxiv.org/html/2409.13740)). Implication (inference): RCS by our
  2B is likely harmful. Prefer trained extractive selectors or sentence-ID selection.
- **Extractive and abstractive compression (RECOMP).** Compression to "as low as 6%"
  with minimal loss. The compressor can return an empty string when documents do not
  help ("selective augmentation")
  ([Xu et al., ICLR 2024](https://arxiv.org/abs/2310.04408)).
- **LongLLMLingua.** Token-level prompt compression: up to +21.4% on NaturalQuestions
  with GPT-3.5-Turbo at about 4x fewer tokens
  ([Jiang et al., ACL 2024](https://arxiv.org/abs/2310.06839)). Token deletion breaks
  verbatim quotes, so it is a poor fit for our quote checks (inference).
- **EXIT.** Sentence-level, context-aware yes/no classification with Gemma-2B. EM gains
  over uncompressed context on NQ, TQA, HotpotQA and 2Wiki with a Llama-3.1-8B reader;
  0.8 s against 8.4 s for CompAct ([2412.12559](https://arxiv.org/html/2412.12559)).
- **Provence.** A unified reranker and sentence pruner, 430M, ICLR 2025 (see item 7).
- **Passage count and order.** Inverted-U with strong retrievers; reorder best-at-ends
  ([Jin et al.](https://arxiv.org/html/2410.05983);
  [Liu et al.](https://arxiv.org/abs/2307.03172)). OpenScholar uses 5–10 passages, at
  most 3 per paper ([2411.14199](https://arxiv.org/html/2411.14199)).

## Area 2: decomposition and two-stage pipelines

- Sub-question methods (least-to-most, self-ask, IRCoT, IterDRAG) improve multi-step QA,
  and IRCoT holds for small Flan-T5 readers (item 5 has the figures).
- Plan-then-write for long-form scientific answers: Ai2 Scholar QA (extract quotes per
  paper → outline → sections, plus generated comparison tables)
  ([2504.10861](https://arxiv.org/html/2504.10861)). OpenScholar adds iterative
  self-feedback, at most three feedback sentences, and citation verification. In its
  ablation, removing feedback barely changed OS-8B (Corr 51.1, Cite 50.2 against 51.3 and
  47.9); removing reranking hurt most (Cite 28.2)
  ([2411.14199](https://arxiv.org/html/2411.14199)).
- Draft from evidence subsets: Speculative RAG drafts in parallel from distinct document
  subsets with a small model, then verifies with a larger one. Up to +12.97% accuracy and
  −50.83% latency on PubHealth ([Wang et al., ICLR 2025](https://arxiv.org/abs/2407.08223)).
  Inference: drafting per facet or per paper with the 2B and choosing with the 4B is the
  same pattern within our hardware.

## Area 3: attribution and citation

- **ALCE.** It scores fluency, correctness and citation recall/precision with an NLI
  model. Even the best models "lack complete citation support 50% of the time" on ELI5
  ([Gao et al., EMNLP 2023](https://arxiv.org/abs/2305.14627)).
- **Attribute-first and quote-first.** Attribute First (AutoAIS 89.3 against 49.8 on
  LFQA) and FRONT (+14.21% citation quality, 7B), in item 1.
- **Fine-grained citation SFT.** LongCite (sentence-index citations, +6.4% citation F1
  over GPT-4o, better correctness) ([2409.02897](https://arxiv.org/html/2409.02897)).
- **Reflection tokens.** Self-RAG 7B/13B reaches ASQA citation precision/recall
  66.9/67.8 and 70.3/71.3; plain retrieval-augmented baselines are often below 6
  ([Asai et al., ICLR 2024](https://arxiv.org/html/2310.11511)). It needs a trained
  model; no Qwen3.5 version exists.
- **Retrieval evaluator (CRAG).** A light evaluator labels retrieval correct, incorrect
  or ambiguous, and a decompose-then-recompose step filters strips of text
  ([Yan et al. 2024](https://arxiv.org/abs/2401.15884)). Our reranker and verifier
  already cover much of this (inference).
- **NLI verification.** MiniCheck and AlignScore (item 8).

## Area 4: abstention and sufficient context

- Definition: context is sufficient if it supports *a* plausible answer. No ground truth
  is needed, and multi-hop reasoning is allowed
  ([2411.06037](https://arxiv.org/html/2411.06037)).
- Small open models over-abstain or hallucinate even with sufficient context. Large
  models over-answer when context is insufficient (same source). Our 57/131 decline rate
  against 0/69 insufficient contexts matches the small-model pattern (inference).
- Fine-tuning Mistral-7B to say "I don't know" on 20% of examples raised abstention only
  slightly (to about 1–2%) and did not raise correctness (unconfirmed table read, same
  source). Naive abstention training is not a cure.
- Trust-Align treats excessive refusal as its own error type and fixes it by preference
  tuning across 0.5B–8B models ([2409.11242](https://arxiv.org/abs/2409.11242)).
  Chain-of-Note improves rejection of truly unknown questions by +10.5
  ([2311.09210](https://arxiv.org/abs/2311.09210)).
- Practical rule (inference): decide sufficiency per facet, with sub-question checks, or
  in code from verified claims, never with one global flag written while drafting.

## Area 5: model choice and training under 4 GiB

| Option | Fits 4 GiB beside retrieval? | Evidence | Note |
| --- | --- | --- | --- |
| Qwen3.5-2B Q4_K_M (current) | yes | card: loop-prone in thinking | baseline |
| Qwen3.5-4B Q4_K_M / IQ4_XS | only if retrieval leaves the GPU (inference) | 3.01 / 2.67 GB files; much higher card scores | best local upgrade candidate |
| Qwen3-4B | same as above | Vectara HHEM summarization: 5.7% hallucination, 99.9% answer rate ([leaderboard](https://github.com/vectara/hallucination-leaderboard), 2026-09-22) | non-hybrid attention, larger KV cache |
| Gemma-3-4B-it | same as above | Vectara: 6.4% hallucination, 67.3% answer rate | low answer rate means more refusals |
| Phi-4-mini, Llama-3.2-3B, SmolLM3 | likely | no grounded-QA numbers found in primary sources for this note | not assessed |
| Pleias-RAG-1B | yes | trained for literal-quote citation ([2504.18225](https://arxiv.org/abs/2504.18225)) | possible extraction model; unverified on science text |
| OpenScholar-8B, Self-RAG-7B/13B, ChatQA | no (GPU); CPU only, slow | strong citation scores in their papers | candidates for CPU-offload or cloud synthesis |
| MiniCheck-FT5 770M, AlignScore 355M | CPU | LLM-AggreFact 74.7 / 70.4 | verifiers, not generators |

- Small models do not use context well: 7B and below fail on 85–100% of oracle-passage
  questions beyond their knowledge, and retrieval context "destroys 42 to 100 percent" of
  answers they already knew ([2603.11513](https://arxiv.org/abs/2603.11513)).
- The Vectara task is short-document summarization judged by HHEM-2.3, not scientific
  QA. Treat it as a weak signal.
- Fine-tuning: see item 10. QLoRA in general fits a 65B model on 48 GB
  ([Dettmers et al., NeurIPS 2023](https://arxiv.org/abs/2305.14314)), but Unsloth
  advises against QLoRA for Qwen3.5, and bf16 LoRA of the 2B needs 5 GB. Not local.

## Area 6: structured output and test-time compute

- **Format restrictions.** JSON mode cut GSM8K accuracy sharply for some models:
  GPT-3.5-Turbo 75.99 → 49.25, Claude-3-Haiku 86.51 → 23.44, LLaMA-3-8B 75.13 → 48.90.
  Gemini-1.5-Flash was unaffected. Answering in natural language first, then converting
  to the format ("NL-to-Format"), gave "nearly identical performance" to free text. In
  JSON mode GPT-3.5 put "answer" before "reason" 100% of the time, removing the reasoning
  step. Classification tasks *improved* under JSON
  ([Tam et al. 2024](https://arxiv.org/html/2408.02442)).
- Inference for us: thinking runs before the JSON, which softens the effect, but key
  order still matters. Put fields so the model writes the evidence sentence IDs, then the
  claim, then the answer. Consider a two-step call: free-text claims, then a cheap
  conversion to JSON in code or a non-thinking call. This is an experiment, not a
  measured fix for our model.
- **Test-time compute.** RAG accuracy rises nearly linearly with inference compute "when
  optimally allocated", but the gain comes from more demonstrations and iterative
  sub-query retrieval, not from longer single-pass thinking
  ([2410.04343](https://arxiv.org/html/2410.04343)). For us (inference), extra compute is
  better spent on more, smaller calls (items 1 and 5) than on longer thoughts in one call.
- **Loops.** Smaller models loop more ([2512.12895](https://arxiv.org/html/2512.12895v1));
  the 2B card warns about it directly.

## Area 7: tables and numbers

- Serialization format and order change accuracy. In one study HTML was best and
  natural language with separators was worst ([2305.13062](https://arxiv.org/html/2305.13062)).
- Making table operations explicit helps (Chain-of-Table,
  [2401.04398](https://arxiv.org/abs/2401.04398)).
- Ai2 Scholar QA builds comparison tables in a separate step: the LLM picks columns from
  abstracts, fills cells from full text, and filters weak rows and columns
  ([2504.10861](https://arxiv.org/html/2504.10861)).
- Inference for us: row-per-unit evidence with headers on every cell (item 9), one row
  per numeric claim, and code-side comparison for cross-paper tables.

## Area 8: evaluation

| Method | What it measures | How we could use it |
| --- | --- | --- |
| Nugget recall (TREC RAG 2024, AutoNuggetizer) | share of key facts ("nuggets") an answer contains; strong run-level agreement between automatic and human nugget scores, weaker per topic ([Pradeep et al., SIGIR 2025](https://arxiv.org/abs/2504.15068)) | our reviewed facets are nuggets: report facet recall per run (today about 23%) |
| RAGChecker | claim-level precision and recall, context utilization, noise sensitivity, faithfulness; better human correlation than other metrics ([Ru et al. 2024](https://arxiv.org/abs/2408.08067)) | context utilization shows whether extraction (item 1) makes the model use more of the pack |
| ALCE | correctness plus NLI-based citation recall and precision ([2305.14627](https://arxiv.org/abs/2305.14627)) | citation precision of kept claims (assistant-reviewed or MiniCheck) |
| LitQA2 (PaperQA2) | accuracy (correct/all) and precision (correct/answered) with an "insufficient information" option ([2409.13740](https://arxiv.org/html/2409.13740)) | report both, so abstention changes are visible |
| ScholarQABench | correctness, citation F1, Prometheus v2 five-point scores, expert rubrics with must-have and nice-to-have items ([2411.14199](https://arxiv.org/html/2411.14199)) | rubric style matches our facet reviews |
| Trust-Score | separates over-responsiveness from excessive refusal (F1_GR) ([2409.11242](https://arxiv.org/abs/2409.11242)) | track decline rate on sufficient contexts, our main failure |

Suggested minimal scorecard per sweep (inference): facet recall, kept claims per run,
kept-claim precision (sampled review), decline rate on contexts reviewed as sufficient,
and verification failure reasons (non-verbatim, number, scope, row). Run replays on
stored evidence, as in the Phase 3 diagnosis, so generator changes are compared on
identical packs.

## Source, setting, model size, measured effect

| Source | Setting | Model size | Measured effect |
| --- | --- | --- | --- |
| [Attribute First (ACL 2024)](https://arxiv.org/html/2403.17104) | LFQA, select → plan → generate | Gemini (ICL); PRIMERA fine-tuned | AutoAIS 89.3 vs 49.8 (ALCE); citations 45x shorter; verification 35 s vs 59 s |
| [FRONT (ACL Findings 2024)](https://arxiv.org/abs/2408.04568) | quote extraction then generation, ALCE-style | LLaMA-2-7B | +14.21% average citation quality, above ChatGPT |
| [LongCite (2024)](https://arxiv.org/html/2409.02897) | sentence-index citations, long-context QA | 8B / 9B | +6.4% citation F1 vs GPT-4o; ~85 vs 220-token citations |
| [EXIT (ACL Findings 2025)](https://arxiv.org/html/2412.12559) | sentence classifier compression | Gemma-2B compressor, Llama-3.1-8B reader | 2Wiki EM 24.2 vs 16.1 uncompressed; 0.8 s latency |
| [RECOMP (ICLR 2024)](https://arxiv.org/abs/2310.04408) | extractive / abstractive compression | small trained compressors | compression to 6% with minimal loss |
| [LongLLMLingua (ACL 2024)](https://arxiv.org/abs/2310.06839) | token compression, NQ | GPT-3.5-Turbo reader | up to +21.4% at ~4x fewer tokens |
| [Provence (ICLR 2025)](https://arxiv.org/abs/2501.16214) | sentence pruning + rerank | 430M DeBERTa-v3 | "negligible to no drop" while pruning |
| [PaperQA2 (2024)](https://arxiv.org/html/2409.13740) | LitQA2, RCS per chunk | GPT-4-Turbo; GPT-3.5 / Llama3-70B | RCS helps with GPT-4-Turbo; weaker RCS models lower accuracy; 5 sources best accuracy |
| [OpenScholar (2024)](https://arxiv.org/html/2411.14199) | ScholarQA-CS | 8B fine-tuned | Cite F1 47.9 vs 24.5 untuned 8B; no rerank → 28.2 |
| [Ai2 Scholar QA (ACL 2025 demo)](https://arxiv.org/html/2504.10861) | ScholarQA-CS, quote → plan → sections | Claude 3.7 | 61.9 vs 53.5 OpenScholar-GPT-4o, 51.4 PaperQA2 |
| [Jin et al. (ICLR 2025)](https://arxiv.org/html/2410.05983) | passage count, reordering | 7B–12B, Gemini | inverted-U with strong retriever; reordering helps at large k (no single number) |
| [Lost in the Middle (TACL)](https://arxiv.org/abs/2307.03172) | multi-doc QA position | various | U-shaped accuracy by position |
| [IRCoT (ACL 2023)](https://arxiv.org/abs/2212.10509) | multi-hop QA | GPT-3, Flan-T5 | retrieval up to +21, QA up to +15 points |
| [IterDRAG (ICLR 2025)](https://arxiv.org/html/2410.04343) | long-context RAG scaling | Gemini 1.5 Flash | up to +58.9% over standard RAG |
| [Speculative RAG (ICLR 2025)](https://arxiv.org/abs/2407.08223) | subset drafting + verifier | small drafter, large verifier | up to +12.97% accuracy, −50.83% latency (PubHealth) |
| [Sufficient Context (ICLR 2025)](https://arxiv.org/html/2411.06037) | abstention analysis | Gemini, GPT-4o, Claude, Gemma, Mistral | selective generation +2–10% correct-among-answered; autorater 93% acc |
| [Trust-Align (ICLR 2025)](https://arxiv.org/abs/2409.11242) | ASQA, QAMPARI, ELI5 | 0.5B–8B | +12.56 / +36.04 / +17.69 (LLaMA-3-8B vs FRONT); 26 of 27 models improved |
| [Chain-of-Note (EMNLP 2024)](https://arxiv.org/abs/2311.09210) | noisy retrieval | LLaMA-2-7B | +7.9 EM noisy docs; +10.5 rejection on unknown |
| [Self-RAG (ICLR 2024)](https://arxiv.org/html/2310.11511) | ASQA citations | 7B / 13B | citation precision 66.9 / 70.3 |
| [RAFT (2024)](https://arxiv.org/html/2403.10131) | domain RAG with distractors | 7B | PubMed 73.30 vs 58.8; quote-CoT +9.66 HotpotQA |
| [InstructRAG (ICLR 2025)](https://arxiv.org/abs/2406.13629) | rationale-based denoising | 8B-class | +8.3% relative over best baseline |
| [MiniCheck (EMNLP 2024)](https://arxiv.org/html/2404.10774) | LLM-AggreFact | 770M | 74.7 vs GPT-4 75.3 bal. acc.; 400x cheaper |
| [AlignScore (ACL 2023)](https://arxiv.org/abs/2305.16739) | factual consistency, 22 datasets | 355M | matches or beats ChatGPT/GPT-4 metrics |
| [Let Me Speak Freely (2024)](https://arxiv.org/html/2408.02442) | JSON mode vs free text | GPT-3.5, Claude Haiku, Llama-3-8B, Gemini Flash | GSM8K drops up to ~63 points; NL-to-Format recovers |
| [Thinking helps/hurts (2026)](https://arxiv.org/abs/2606.09662) | instruction constraints | Qwen3 1.7B–32B | thinking worsens exact-form constraints; 10–20% prompts flip |
| [Pandey et al. (2026)](https://arxiv.org/abs/2603.11513) | oracle-passage QA | 360M–8B | ≤7B fail 85–100% beyond own knowledge |
| [Table Meets LLM (WSDM 2024)](https://arxiv.org/html/2305.13062) | table serialization | GPT-3.5 / GPT-4 | HTML +6.76% over NL+separators; +0.84–5.68% downstream |

## Open questions to measure on our replays

1. Does per-passage sentence-ID extraction (items 1–2) raise kept claims and facet
   recall on stored evidence, and at what latency?
2. Does Qwen3.5-4B fit on the GPU once retrieval models are unloaded, and how fast is it?
3. Thinking against non-thinking for extraction calls: claims kept, loops, time.
4. With the generator's insufficiency flag removed (item 6), how much does precision of
   kept claims fall, if at all?
5. Does MiniCheck-FT5 agree with assistant review of kept and dropped claims on a
   sample of Phase 3/4 claims?

## Addendum: trials on stored evidence (2026-10-11)

Assistant-run and assistant-reviewed. One sample per question on the 21 development
questions, scored with the project's claim checks (`verify_claim`, quote fallback,
`decide_outcome`). "Supported and relevant" is the assistant's judgement of each kept
claim against its question. Run-to-run variation is large, so differences of a few claims
are within noise. Inputs, outputs and scripts are private under `local-reference/phase4/`.

### Granite 3.3 2B and IBM's RAG adapters

The 2B adapters in [`ibm-granite/rag-intrinsics-lib`](https://huggingface.co/ibm-granite/rag-intrinsics-lib)
(answerability, citations, hallucination detection) ran on llama.cpp's server. Ollama
0.35 no longer loads LoRA adapters, and it produced repeated tokens from Granite
converted at Q8_0 while Q4_K_M worked.

| Setup (trace inputs) | Kept claims | Supported and relevant | Declined |
| --- | ---: | ---: | ---: |
| Qwen3.5-2B, stored outputs | 28 | about 24 (86%) | 8 |
| Granite, same prompt and JSON schema | 69 | about 24 (35%) | 1 |
| Granite + answerability gate + plain answer + citations adapter | 26 | about 19 (73%) | 6 |

- The Granite JSON writer wrote one claim per passage whether or not it answered the
  question; such claims pass verification because their quotes are real.
- The answerability adapter declined 5 questions; 4 were "does any paper report X?"
  questions where no paper does.
- Granite took about 15–40 s per question without thinking; Qwen took 2–7 min with it.

### Extract-first with Granite (recommendation 1)

Each passage was sent alone with its sentences or table rows numbered; Granite returned
the numbers that answer the question; the writer saw only the selected units, and claims
were verified against the full passages. Widening prose passages with neighbouring
chunks was dropped: retrieved prose passages are already section-sized and usually the
only text chunk in their section.

| Setup (export inputs) | Kept claims | Supported and relevant | Declined | Claims citing a judged paper |
| --- | ---: | ---: | ---: | ---: |
| Qwen3.5-2B, stored outputs | 32 | about 28 (88%) | 7 | 15 (7 of 10 questions) |
| Granite direct | 71 | about 19 (27%) | 1 | 18 (9 of 10) |
| Granite extract-first | 66 | about 27 (41%) | 0 | 24 (10 of 10) |

- Selection kept 236 of 540 passages but 59 of 77 passages from judged papers.
- Extract-first raised Granite's supported-and-relevant claims by about 40%, but Granite
  still adds irrelevant claims, so neither Granite setup matches Qwen's precision.

### Conclusions

- Qwen3.5-2B stays the generator; no Granite setup improved precision-weighted quality.
- Per-passage selection finds the relevant evidence and is the most promising component.
  The untested combination is Granite (or Qwen without thinking) selecting and Qwen
  writing from the selections.
- The 100K-token context fits on the GPU beside retrieval with 166 MiB to spare, but no
  request uses it: the largest stored prompt is 8,680 tokens, and the pack budget never
  omitted a passage in 42 runs. The default stays 32,768.
