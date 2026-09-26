# BM25S dependency research for P2-06.1

**Reviewed:** 2026-09-26

**Reviewer:** Assistant (Codex, under the user's Phase 2 delegation)
**Scope:** Primary-source review of BM25S release, API, filtering, license and
local index artifacts. This is research input to the pilot, not package
acceptance.

## Finding

Target **`bm25s==0.3.11`** for the bounded pilot. PyPI lists 0.3.11 as the latest
release, uploaded 2026-08-25, requires Python `>=3.8`, and declares MIT. The
wheel is `py3-none-any`; its SHA-256 is
`3d1d28badb299d6fc9324111e5c8276927e990b908607b39ff9bd65b102e9a24`. PyPI's
attestation identifies the publishing repository and source commit. The
repository's Python 3.12 environment satisfies the declared version floor.
The exact wheel was later installed only under `/tmp` and its hash matched PyPI;
the project's environment and dependency files were not changed. [PyPI release
metadata and attestation](https://pypi.org/project/bm25s/0.3.11/), [upstream MIT
license at the attested commit](https://github.com/xhluca/bm25s/blob/a213158181d4b3781ba06bc88840f89871f1c775/LICENSE).

The core package uses NumPy and does not require Java or PyTorch. Numba and
stemming are optional. Since BM25S 0.3.0, SciPy is not required for the default
NumPy CSC builder; SciPy is an optional indexing choice. Avoid selecting extras
until the analyzer and backend are measured. [Upstream installation and API
guide](https://github.com/xhluca/bm25s), [maintainer's 0.3.0 release
notes](https://github.com/xhluca/bm25s/discussions/167).

The package is a plausible local lexical candidate, but it is **not yet accepted
as a project dependency**. The current finalized snapshot has 100 papers and
44,277 expected evidence chunks, the workload used by the P2 pilot.
[Phase 1 acceptance report](../reference/phase-1-100-paper-acceptance-report.md).

## API and eligibility filtering

The documented low-level path is `bm25s.tokenize(corpus)`, `BM25().index(...)`,
then `retrieve(tokenized_query, k=...)`; retrieval returns document positions
and scores. Optional corpus entries are looked up by the same row position, so
the application must keep a stable row-to-evidence-ID mapping. The index can
store IDs as corpus entries without storing source passages. [Upstream quick
start and corpus format](https://pypi.org/project/bm25s/0.3.11/).

`retrieve` exposes `weight_mask`, but it does **not** guarantee hard eligibility
before top-k. In the current source, the mask multiplies scores by zero and
normal top-k is then run across the full document score vector. Consequently,
masked documents can tie with eligible zero-score documents and may be returned
when fewer than `k` eligible documents have positive scores (including no-term
matches). The maintainer also confirmed that this still computes over the full
corpus; subset-only scoring is not currently implemented. Treat the mask as a
score modifier, not a strict filter or a subset-scoring optimization.
[Upstream retrieval source](https://github.com/xhluca/bm25s/blob/a213158181d4b3781ba06bc88840f89871f1c775/bm25s/__init__.py),
[maintainer discussion on subset retrieval](https://github.com/xhluca/bm25s/discussions/82).

BM25S can still be evaluated for the project if the adapter applies top-k only
over authoritative eligible row IDs (or a separately built eligible index) and
returns empty for zero eligible IDs. The pilot should explicitly exercise
restrictive filters, zero eligible IDs, no term matches, and fewer than `k`
matching eligible records. A `weight_mask`-only implementation does not meet
P2-06.4's filter contract.

## Artifacts and reproducibility

`BM25.save(...)` writes multiple local files: sparse score data, indices and
indptr arrays, vocabulary and scoring parameters, with optional non-occurrence
data and a JSONL corpus mapping. `BM25.load(..., mmap=True)` supports
memory-mapped loading; upstream also documents a `load_corpus` option. Store
only stable evidence IDs in any persisted corpus mapping, not source text.
BM25S's `Tokenizer` has separate save/load methods for vocabulary and stopwords;
splitter, stemming implementation and other analyzer choices still need
versioned configuration in the project manifest. [Upstream save/load and
tokenizer guide](https://github.com/xhluca/bm25s), [save implementation and
file list](https://github.com/xhluca/bm25s/blob/a213158181d4b3781ba06bc88840f89871f1c775/bm25s/__init__.py).

Upstream reports memory-mapped measurements on Natural Questions (2M+ docs)
and MSMARCO (8M+ docs), but these are upstream workloads and hardware, not
capacity evidence for this project's 44,277 chunks. The library serializes a
multi-file directory; project-side compatibility validation, checksums and
atomic publication still need to be demonstrated under P2-06.5. [Upstream
memory-mapping results](https://pypi.org/project/bm25s/0.3.11/).

The package is MIT-licensed. Upstream separately acknowledges that
`bm25s.utils.beir.evaluate` comes from BEIR and follows Apache-2.0; keep that
attribution if the project uses that utility. The pilot need not use it.
[Upstream license](https://github.com/xhluca/bm25s/blob/main/LICENSE),
[upstream acknowledgement](https://pypi.org/project/bm25s/0.3.11/).

## Pilot implications

The bounded pilot used the exact permission-approved chunks selected by snapshot
`4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` in `research_phase1_review`. A read-only
join applied each member's configured chunk selection and required both artifact
and immutable permission evidence to allow indexing. It returned 100 papers and
44,277 unique chunks, matching the accepted entry count; UTF-8 evidence text totaled
11,515,624 bytes. The sorted row-to-evidence-ID manifest fingerprint was
`sha256:a736b914cc350f60039a81b1944214983526c3423206109bf664abb985264dae`.
No database writes, migration, source changes, or model downloads occurred.

### Measured local pilot — 2026-09-26

The tested artifact was `bm25s==0.3.11`, wheel SHA-256
`3d1d28badb299d6fc9324111e5c8276927e990b908607b39ff9bd65b102e9a24`, on Python
3.12.14 and NumPy 2.5.3. Both the BM25 backend and CSC builder were forced to
`numpy`. The pilot used BM25S's default tokenization only as a baseline: lowercase,
two-character word tokens, English stopwords and no stemmer. The selected
custom analyzer is versioned as `scientific-en-v1`; its policy and measured token
retention are in [phase-2-bm25s-analyzer.md](../reference/phase-2-bm25s-analyzer.md).
BM25S's `lucene` default uses Lucene IDF and the
Robertson term-frequency component; explicit `k1=1.5`, `b=0.75` scoring matched
an independent three-document calculation within `1e-6` absolute tolerance and
produced the expected order. [Pinned BM25S scoring source](https://github.com/xhluca/bm25s/blob/a213158181d4b3781ba06bc88840f89871f1c775/bm25s/scoring.py).

| Measurement | Result |
|---|---:|
| Analyzed chunks / papers | 44,277 / 100 |
| UTF-8 source-text bytes | 11,515,624 |
| Analyzed token count / vocabulary size | 1,345,214 / 43,469 |
| Corpus read from the local export | 0.217 s |
| Tokenization | 0.626 s |
| Sparse index build | 0.702 s |
| Save | 0.233 s |
| Serialized index directory | 14,136,065 bytes |
| Build-process peak RSS | 140.07 MiB |
| `mmap=True` reload in a separate process, two runs | 0.019–0.020 s |
| Saved row-to-evidence-ID validation, two runs | 0.070–0.071 s |
| RSS after mmap load / peak after queries, two runs | 78.54–79.16 / 88.02–88.30 MiB |
| Warm full-corpus query median / p95, two runs | 1.409–1.444 / 1.997–2.223 ms |
| Warm restrictive-filter query median / p95, two runs | 1.192–1.229 / 1.689–1.975 ms |

Query latency includes query tokenization, the full score-vector calculation and
eligible-only top-k selection; it excludes database access and the resolution of
eligible IDs. Two independent timing replays each ran 25 repeats of ten
canonical `calibration-v1` queries per scope (250 queries per scope per replay).
The mmap reload ran in a new process but the OS file cache was warm after index
creation, so it is not a cold-storage measurement. Process RSS includes Python/
NumPy runtime overhead and is not a host-wide memory delta. The saved BM25S JSONL
corpus file contains only row numbers and stable evidence IDs, not passages.
The wheel, export SQL, source script, index and aggregate metrics are retained in
the git-ignored private run directory
`local-reference/phase2-runs/bm25s-pilot-2026-09-26/`; its README records replay
commands.

### Filtering result

The pilot reproduced the `weight_mask` failure with a synthetic corpus: for one
eligible positive document and `k=2`, `retrieve(weight_mask=...)` returned an
ineligible document with score zero. The source confirms that the mask multiplies
scores before top-k, so it cannot implement strict eligibility. The compatible
path is `get_scores(query_tokens)`, then intersect positions with authoritative
eligible IDs and select top-k only from that subset; trim zero-score results and
return empty for no eligible rows or no positive matches.

On the accepted corpus, a five-paper filter resolved to 1,329 eligible chunks.
Across the ten calibration queries, filtering global top-50 results afterward
returned zero eligible hits, while eligible-only top-k returned 260 total hits.
All results from eligible-only selection passed the filter; a singleton eligible
row never exceeded one result; zero eligibility and a verified out-of-vocabulary
query returned empty. These are filter-correctness observations, not retrieval
quality scores.

This makes BM25S **feasible as a candidate** for the next implementation steps:
it has low measured local build/storage cost, fast warm scoring at this corpus
scale, stable row mapping and a correct adapter path for restrictive filters.
The API's masked `retrieve` path is disallowed for project filtering. P2-06.2
now defines the scientific analyzer; P2-06.3–06.5 must implement and validate
serving artifacts, rebuild, and CLI behavior. No dependency or serving code has
been added, and the lexical implementation ADR remains deferred until that task
is complete.

## Agent operating checklist

- This serves Phase 2 P2-06.1. BM25 is approved. The scientific-en-v1 analyzer
  is defined in P2-06.2; the BM25S package remains a measured candidate until
  implementation and lifecycle checks finish.
- This research adds no service or duplicate search logic. The pilot covered
  exact scoring/order, eligible-only top-k, empty eligibility, zero-term queries,
  and mmap save/load with the stable ID mapping. Atomic rebuild publication and
  the serving CLI remain for P2-06.5.
- Record peak memory, build/query times and storage with the snapshot, code,
  dependency and analyzer identities. The small local profile must not download
  models.
- MIT licensing is compatible with local use; the optional BEIR utility has an
  Apache-2.0 attribution. No excluded technology is proposed.
- A P2-06 implementation ADR and dependency/config update belong after P2-06.2–
  06.5 implement the chosen analyzer and pass their done conditions; this note
  does not change the source of truth.

## Ambiguities and source dates

PyPI identifies 0.3.11 as current and records its 2026-08-25 upload, while the
GitHub Releases page reviewed still showed 0.3.10 (2026-07-22) as its latest
formal release. PyPI's attestation links the 0.3.11 artifacts to upstream commit
`a213158181d4b3781ba06bc88840f89871f1c775`; before accepting a runtime pin,
compare behavior against that immutable commit and retain the artifact hash.
[PyPI attestation](https://pypi.org/project/bm25s/0.3.11/), [GitHub
releases](https://github.com/xhluca/bm25s/releases).

Sources were accessed on 2026-09-26. Relevant source dates: PyPI 0.3.11,
2026-08-25; GitHub 0.3.10 release, 2026-07-22; maintainer 0.3.0 notes,
2026-02-17; subset-retrieval discussion, 2024-11-13, later updated with a maintainer
subset-scoring reply on 2026-07-06 and follow-up on 2026-07-08. Upstream `main` README,
retrieval source and license are mutable URLs, so the release artifact
attestation should be used to identify the code version during the later pilot.
