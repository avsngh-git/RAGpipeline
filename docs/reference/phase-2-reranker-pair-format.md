# Phase 2 reranker pair format

Status: implemented and assistant-reviewed for P2-10.2, 2026-09-27.

The versioned pair format is query-source-chunk-v1, implemented by
search/reranker_pairs.py.

## Pair content

For each candidate, the cross-encoder receives one tokenizer pair:

1. The original query string, unchanged.
2. The complete stored EvidenceHit.text, unchanged.

Version 1 adds no paper title, section heading, abstract, query instruction or
other context. EvidenceHit does not currently carry section metadata or structured
table records, so the pair builder does not guess or fetch additional fields. The
pair retains its chunk ID, source evidence IDs and original fused rank alongside
the model inputs.

The stored table-row-group text already carries source associations from ingestion:
caption and units when available, repeated header rows, row/column context, and cell
values. The regular row-group renderer also includes table footnotes. The oversized
cell renderer preserves caption/units, applicable row and column headers, cell
coordinates and value. Pair formatting copies the entire stored string; it never
parses, clips, flattens again or detaches a value from its header. Any context absent
from that stored string remains absent from this pair version.

## Token budget and overflow

The maximum pair length is 512 tokens, including query tokens, paired-input special
tokens and evidence text. Each candidate model revision provides a token counter that
counts the complete pair with truncation disabled. The builder accepts a mapping of
tokenizer identities to counters:

- A serving run supplies the selected model tokenizer.
- A comparative run supplies both shortlisted model/tokenizer revisions, ensuring
  every candidate is represented identically and fits both budgets.

If any candidate exceeds 512 for any supplied tokenizer, pair construction raises
RerankerPairBudgetExceeded with the candidate IDs and measured counts. It returns
no partial pair list, does not shorten or discard the offending evidence, and does
not rerank only the remaining candidates. The later orchestration step handles this
as an explicit reranker failure and returns the unchanged fused ranking. A future
windowing policy must preserve source offsets/IDs and receive a new pair-format ID.

Input order and original fused ranks are retained for deterministic tie handling.
Raw cross-encoder scores remain separate from prior lexical, dense and fusion
components. They are not part of pair formatting and are not treated as
probabilities.

## Limits

This pair version has not yet been evaluated for retrieval quality. It deliberately
uses source chunk text as ingested; it does not synthesize a title or section from
paper metadata. Oversized-cell evidence can lack table-level footnotes in the stored
text, because the ingestion renderer does not associate those notes with individual
cells. Correcting that would require a source-aware representation change, not
inference-time guessing.
