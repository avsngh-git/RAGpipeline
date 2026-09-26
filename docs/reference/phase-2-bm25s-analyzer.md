# Phase 2 BM25S analyzer v1

**Status:** selected reversible development analyzer for P2-06

**Reviewer:** Assistant (Codex, under the user's Phase 2 delegation)
**Measured:** 2026-09-26 on the accepted 100-paper snapshot

## Identity

The analyzer is implemented in src/research_platform/search/lexical_analyzer.py.
Its version fields are intended to flow into LexicalIndexIdentity and the
retrieval profile when the lexical index is built.

| Field | Value |
|---|---|
| Analyzer ID | scientific-en |
| Analyzer revision | v1 |
| Normalization revision | unicode-nfc-casefold-dashes-micro-v1 |
| Token-pattern revision | scientific-compound-number-operator-v1 |
| Stopword removal | None |
| Stemming | None |
| BM25S baseline implementation | 0.3.11 candidate; project dependency not yet accepted |

## Tokenization policy

- Apply Unicode NFC, Unicode casefolding and a narrow normalization for common
  Unicode dash/minus glyphs. Normalize the micro sign to Greek small mu so
  equivalent micro-unit spellings share an analyzed form.
- Keep one-character terms, acronyms, Unicode letters and alphanumeric codes.
- Keep exact numeric forms, including decimal/group separators, signs, ratios,
  percentages and per-mille values. Emit components for punctuated numeric terms
  as additional aliases; do not round, convert units or discard the original form.
- Keep technical compounds as one token and emit their letter/number components.
  This supports queries such as model/version names and hyphenated methods without
  requiring the query and source to use identical punctuation.
- Preserve comparison/arithmetic symbols as tokens. The analyzer does not infer
  mathematical equivalence: for example, a written symbol and a word such as
  “greater” remain distinct.
- Apply the same analyzer to queries and indexed text. The function returns tokens
  only; source text, offsets and evidence records remain unchanged.

No stopwords are removed because negation and qualifiers such as “no”, “not” and
“without” can change a scientific finding. Stemming is disabled to preserve the
identity of acronyms, model names, metrics and numeric forms. The wider token
set costs index space and can increase noise; development evaluation may revise
this choice under a new analyzer revision.

## Accepted-corpus measurement

The comparison used the permission-approved 44,277 selected chunks from snapshot
4b11fab3-d4a5-4e7a-a58e-8654accf2c6c. The BM25S-default column is a diagnostic
baseline only; it uses lowercase two-character word tokens, English stopwords and
no stemmer. The scientific analyzer is custom Python tokenization passed to BM25S.
No relevance labels or ranked-result quality metrics were used in this comparison.

| Measure | BM25S default baseline | scientific-en-v1 |
|---|---:|---:|
| Tokenization time | 0.511 s | 2.012 s |
| Token count | 1,345,214 | 1,917,082 |
| Vocabulary size | 43,469 | 65,432 |
| Chunks with no analyzed tokens | 3,685 | 601 |
| Distinct canonical-query token types found in corpus vocabulary | 173 / 174 | 230 / 236 |
| Tokens retained from a fixed 10-term diagnostic | 1 / 10 | 10 / 10 |

The custom analyzer adds 571,868 token occurrences (42.5%) and 21,963 vocabulary
terms (50.5%) relative to the BM25S-default baseline. The ten diagnostic features
cover negation, a one-character variable, a scientific model/version form, a
hyphenated retrieval setting, decimal and percentage values, a ratio and a
comparison operator. Seven of the ten calibration question families contain at
least one one-character query token. The canonical query text and diagnostic term
values are intentionally not included here.

These counts show preservation and local feasibility, not better relevance
ranking. The two query-token vocabulary counts have different denominators because
the analyzer policies emit different terms; they are not comparable quality
scores. The custom tokenization pass took about two seconds for 44,277 chunks on
the pilot host. No stemming/stopword grid or held-out labels were used.

## Verification and next use

Nine focused tests cover identity fields, casefolding, one-character terms,
stopwords/negation, compounds, numeric aliases, operators, dash and micro
normalization, punctuation-only inputs and invalid types. On this revision:

- pytest -q tests/test_lexical_analyzer.py: 9 passed
- ruff check on the analyzer and test: passed
- ruff format --check on the analyzer and test: passed
- mypy on the analyzer and test: passed

P2-06.3 will use this analyzer for the evidence index and apply a separately named
representation to paper title/abstract records. Later development evaluation may
select a different analyzer, but the change must receive a new versioned identity
and rebuild its lexical artifacts. BM25S remains a candidate until P2-06.3–06.5
complete index, filter, reload, rebuild and CLI validation.
