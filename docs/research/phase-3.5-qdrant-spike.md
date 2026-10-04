# Phase 3.5 Qdrant compatibility spike (P35-02)

Date: 2026-10-04. Card: P35-02 ([#46](https://github.com/avsngh-git/RAGpipeline/issues/46)).
Script: [`scripts/phase35_qdrant_spike.py`](../../scripts/phase35_qdrant_spike.py), run against a
disposable container with no volume:

```bash
docker run -d --rm --name qdrant-spike -p 127.0.0.1:6340:6333 qdrant/qdrant:v1.19.1
python scripts/phase35_qdrant_spike.py --url http://127.0.0.1:6340
```

The script uses an 8-point toy corpus. Its sparse vectors hold BM25S Lucene term-frequency
weights (`k1=1.5`, `b=0.75`). It compares Qdrant scores with Lucene IDF computed in Python.
One point has an empty token list, matching BM25S rows with no tokens.

## Decisions

| Question | Answer |
| --- | --- |
| Pinned version | `qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10` (latest stable on 2026-10-04; server commit `6ab21cac`) |
| **Parity possible** | **Yes.** Qdrant's IDF modifier equals Lucene IDF `ln(1 + (N - df + 0.5) / (df + 0.5))` within 1.4e-7 relative. With the IDF corpus filter, `N` counts every point matching the filter, including points with an empty sparse vector, which is how BM25S counts documents. Every lexical query must therefore send the IDF corpus filter; without it, `N` excludes empty points and scores differ. |
| IDF corpus filter with the generation condition | Works. Scores for generations 1 and 2 match expectations computed over exactly that generation's visible points. |
| Repeated query token | Counts twice when sent as weight 2, matching BM25S `get_scores`. |
| Docling GPU use | From code: `--device auto` maps to Docling `AcceleratorDevice.AUTO`, which selects CUDA when available (Docling documentation; not measured). **Docling is not installed** in any local Conda environment (the `pdf` extra is missing), so P35-24 must install `.[pdf]` and measure GPU use. |
| Upgrade method | Storage compatibility is only guaranteed across one minor version ([Qdrant upgrades](https://qdrant.tech/documentation/upgrades/)), so an in-place 1.14 → 1.19 upgrade must step through 1.15, 1.16, 1.17 and 1.18. Every local collection is rebuildable, so instead export each collection's points (vectors and payloads) over REST, start v1.19.1 on a **new** volume, import, and check exact counts. Keep the old volume `ragpipeline_qdrant_data` untouched for rollback. CI uses fresh service containers and only needs the new pin. |

Local collections on 2026-10-04: `phase2-dev-gte-modernbert-base-v1` (44,277),
`phase2-e5-small-v2-filtered` (44,277), `phase1-e5-small-v2` (53,961) and
`phase2-bge-base-en-v1-5` (44,277).

## Facts

| Step | Result |
| --- | --- |
| Named dense plus named sparse vector with `modifier: idf` | Created. |
| Upsert with an empty sparse vector (`indices: []`) | Accepted. |
| Sparse query, no filter (global IDF) | Matches Lucene only when `N` and `df` exclude empty points (relative difference 1.1e-7; 0.17 when the empty point is counted). |
| Sparse query with retrieval filter and IDF corpus filter = generation 1 | Matches Lucene over the 5 visible points including the empty one (7.0e-8). |
| Same for generation 2 | Matches (1.1e-7). |
| Default global IDF with a generation retrieval filter | Differs from generation-scoped expectations (0.17): the corpus filter is required. |
| Repeated query token as weight 2 | Matches BM25S counting (1.4e-7). |
| Exact count with generation filter plus `lexical_terms` match-any | 3 observed, 3 expected. |
| Batch query (dense and sparse searches) | Returns one result list per search. |
| Set `retired_generation` through set-payload | Generation counts 5 and 5 as expected after retirement. |
| `recommend` query on the dense vector | Returns results; the source point is excluded with `has_id` in `must_not`. |
| Retrieve points by ID | Returns them in request order (7, 3, 6). Callers should still re-order by ID. |

## JSON shapes that worked

Collection:

```json
PUT /collections/{name}
{"vectors": {"dense": {"size": 768, "distance": "Cosine"}},
 "sparse_vectors": {"scientific_bm25": {"modifier": "idf"}}}
```

Point vectors:

```json
{"id": "<uuid>", "vector": {"dense": [...], "scientific_bm25": {"indices": [3, 17], "values": [0.41, 0.62]}},
 "payload": {...}}
```

Generation filter (visible in generation N):

```json
{"must": [
  {"key": "added_generation", "range": {"lte": N}},
  {"should": [
    {"is_empty": {"key": "retired_generation"}},
    {"key": "retired_generation", "range": {"gt": N}}]}]}
```

Sparse query with the IDF corpus filter (the corpus filter sits in `params.idf.corpus`):

```json
POST /collections/{name}/points/query
{"query": {"indices": [...], "values": [...]}, "using": "scientific_bm25",
 "filter": <generation filter plus search conditions>,
 "params": {"idf": {"corpus": <generation filter>}},
 "limit": 60, "with_payload": true}
```

Exact count:

```json
POST /collections/{name}/points/count
{"exact": true, "filter": {"must": [<generation conditions>, {"key": "lexical_terms", "match": {"any": ["bm25"]}}]}}
```

Batch query:

```json
POST /collections/{name}/points/query/batch
{"searches": [{"query": [...], "using": "dense", "limit": 50},
              {"query": {"indices": [...], "values": [...]}, "using": "scientific_bm25", "limit": 50}]}
```

Set payload:

```json
POST /collections/{name}/points/payload?wait=true
{"payload": {"retired_generation": 2}, "points": ["<uuid>", "<uuid>"]}
```

Recommend:

```json
POST /collections/{name}/points/query
{"query": {"recommend": {"positive": ["<uuid>"]}}, "using": "dense",
 "filter": {"must_not": [{"has_id": ["<uuid>"]}]}, "limit": 10}
```

## Consequences for later cards

- P35-05: `query_sparse` must always send `params.idf.corpus`. Retrieve results should be re-ordered by requested ID.
- P35-11/P35-12: empty-token chunks must still be upserted as points (with an empty sparse vector) so that `N` matches BM25S.
- P35-13: the IDF corpus filter for evidence is the generation filter; for papers it is the indexed-paper filter.
- P35-03: export/import to a new volume instead of an in-place multi-version upgrade.
- P35-24: install the `pdf` extra before any extraction work.
