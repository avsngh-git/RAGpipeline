"""Phase 3.5 compatibility spike: check the Qdrant features later cards depend on.

Run against a disposable Qdrant container, for example:

    docker run -d --rm --name qdrant-spike -p 127.0.0.1:6340:6333 qdrant/qdrant:<tag>
    python scripts/phase35_qdrant_spike.py --url http://127.0.0.1:6340

The script creates and deletes one collection named ``phase35-spike`` and prints a JSON
facts report. It never touches application data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

COLLECTION = "phase35-spike"
K1 = 1.5
B = 0.75

# Token lists stand in for scientific-en-v1 output; generation tags exercise visibility.
DOCUMENTS: tuple[dict[str, Any], ...] = (
    {"id": 1, "tokens": ["bm25", "retrieval", "ndcg@10", "ndcg", "10"], "added": 1},
    {
        "id": 2,
        "tokens": ["dense", "retrieval", "retrieval", "gpt-3.5", "gpt", "3", "5"],
        "added": 1,
    },
    {"id": 3, "tokens": ["reranking", "cross", "encoder", "bm25"], "added": 1},
    {
        "id": 4,
        "tokens": ["table", "0.5%", "0.5", "accuracy", "bm25", "bm25"],
        "added": 1,
        "retired": 2,
    },
    {"id": 5, "tokens": [], "added": 1},
    {"id": 6, "tokens": ["hybrid", "retrieval", "fusion", "rrf"], "added": 2},
    {"id": 7, "tokens": ["bm25", "sparse", "vectors"], "added": 2},
    {"id": 8, "tokens": ["dense", "vectors", "ndcg@10"], "added": 2},
)


def generation_filter(generation: int) -> dict[str, object]:
    return {
        "must": [
            {"key": "added_generation", "range": {"lte": generation}},
            {
                "should": [
                    {"is_empty": {"key": "retired_generation"}},
                    {"key": "retired_generation", "range": {"gt": generation}},
                ]
            },
        ]
    }


def vocabulary() -> dict[str, int]:
    terms = sorted({token for doc in DOCUMENTS for token in doc["tokens"]})
    return {term: index for index, term in enumerate(terms)}


def tf_weights(tokens: Sequence[str], average_length: float) -> dict[str, float]:
    counts = Counter(tokens)
    norm = K1 * ((1 - B) + B * len(tokens) / average_length)
    return {term: tf / (norm + tf) for term, tf in counts.items()}


def lucene_idf(df: int, n: int) -> float:
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


def expected_scores(
    query: Sequence[str], population: Sequence[Mapping[str, Any]], average_length: float
) -> dict[int, float]:
    n = len(population)
    df = Counter(term for doc in population for term in set(doc["tokens"]))
    query_counts = Counter(query)
    scores: dict[int, float] = {}
    for doc in population:
        weights = tf_weights(doc["tokens"], average_length)
        score = sum(
            lucene_idf(df[term], n) * weights[term] * count
            for term, count in query_counts.items()
            if term in weights
        )
        if score > 0:
            scores[doc["id"]] = score
    return scores


def sparse(
    weights: Mapping[str, float], vocab: Mapping[str, int]
) -> dict[str, list[Any]]:
    items = sorted(
        (vocab[term], value) for term, value in weights.items() if term in vocab
    )
    return {"indices": [i for i, _ in items], "values": [v for _, v in items]}


async def call(
    http: httpx.AsyncClient, method: str, path: str, body: object | None = None
) -> dict[str, Any]:
    response = await http.request(method, path, json=body)
    if response.status_code >= 400:
        raise RuntimeError(
            f"{method} {path} -> {response.status_code}: {response.text}"
        )
    return response.json()


def visible(generation: int) -> list[Mapping[str, Any]]:
    return [
        doc
        for doc in DOCUMENTS
        if doc["added"] <= generation
        and ("retired" not in doc or doc["retired"] > generation)
    ]


def compare(
    observed: Mapping[int, float], expected: Mapping[int, float]
) -> dict[str, object]:
    ids_equal = set(observed) == set(expected)
    diffs = [abs(observed[i] - expected[i]) for i in expected if i in observed]
    rel = [
        abs(observed[i] - expected[i]) / expected[i] for i in expected if i in observed
    ]
    return {
        "ids_equal": ids_equal,
        "max_abs_diff": max(diffs, default=0.0),
        "max_rel_diff": max(rel, default=0.0),
    }


async def sparse_scores(
    http: httpx.AsyncClient,
    query: Sequence[str],
    vocab: Mapping[str, int],
    *,
    filter_: Mapping[str, object] | None,
    idf_corpus: Mapping[str, object] | None,
) -> dict[int, float]:
    body: dict[str, object] = {
        "query": sparse(dict(Counter(query)), vocab),
        "using": "scientific_bm25",
        "limit": 20,
        "with_payload": False,
    }
    if filter_ is not None:
        body["filter"] = filter_
    if idf_corpus is not None:
        body["params"] = {"idf": {"corpus": idf_corpus}}
    result = await call(http, "POST", f"/collections/{COLLECTION}/points/query", body)
    return {int(p["id"]): float(p["score"]) for p in result["result"]["points"]}


async def run(url: str) -> dict[str, object]:
    facts: dict[str, object] = {}
    vocab = vocabulary()
    async with httpx.AsyncClient(base_url=url, timeout=30) as http:
        facts["server"] = (await call(http, "GET", "/"))["version"]
        await http.delete(f"/collections/{COLLECTION}")
        create_body = {
            "vectors": {"dense": {"size": 4, "distance": "Cosine"}},
            "sparse_vectors": {"scientific_bm25": {"modifier": "idf"}},
        }
        await call(http, "PUT", f"/collections/{COLLECTION}", create_body)
        facts["create_collection_body"] = create_body
        for field, schema in (
            ("added_generation", "integer"),
            ("retired_generation", "integer"),
            ("lexical_terms", "keyword"),
            ("paper_id", "keyword"),
        ):
            await call(
                http,
                "PUT",
                f"/collections/{COLLECTION}/index?wait=true",
                {"field_name": field, "field_schema": schema},
            )

        # Weights use the generation-1 average length; IDF comes from Qdrant at query time.
        average_length = sum(len(d["tokens"]) for d in visible(1)) / len(visible(1))
        points = []
        for doc in DOCUMENTS:
            payload: dict[str, object] = {
                "evidence_id": f"e{doc['id']}",
                "paper_id": f"p{doc['id'] % 3}",
                "added_generation": doc["added"],
                "lexical_terms": sorted(set(doc["tokens"])),
            }
            if "retired" in doc:
                payload["retired_generation"] = doc["retired"]
            vector: dict[str, object] = {
                "dense": [float(doc["id"]), 1.0, float(len(doc["tokens"])), 0.5],
                "scientific_bm25": sparse(
                    tf_weights(doc["tokens"], average_length), vocab
                ),
            }
            points.append({"id": doc["id"], "vector": vector, "payload": payload})
        await call(
            http,
            "PUT",
            f"/collections/{COLLECTION}/points?wait=true",
            {"points": points},
        )
        facts["empty_sparse_vector_upsert"] = "accepted"

        # 3. Formula check with all points in the IDF population (no filters).
        query = ["bm25", "retrieval", "ndcg@10"]
        observed = await sparse_scores(
            http, query, vocab, filter_=None, idf_corpus=None
        )
        expected_all = expected_scores(query, DOCUMENTS, average_length)
        expected_non_empty = expected_scores(
            query, [d for d in DOCUMENTS if d["tokens"]], average_length
        )
        facts["global_idf_counting_empty_points"] = compare(observed, expected_all)
        facts["global_idf_excluding_empty_points"] = compare(
            observed, expected_non_empty
        )

        # 4. Repeated query token.
        repeated = ["bm25", "bm25", "retrieval"]
        observed_rep = await sparse_scores(
            http,
            repeated,
            vocab,
            filter_=generation_filter(2),
            idf_corpus=generation_filter(2),
        )
        facts["repeated_query_token_counts_twice"] = compare(
            observed_rep, expected_scores(repeated, visible(2), average_length)
        )

        # 5. Generation filter plus IDF corpus filter.
        for generation in (1, 2):
            gen_filter = generation_filter(generation)
            observed_gen = await sparse_scores(
                http, query, vocab, filter_=gen_filter, idf_corpus=gen_filter
            )
            facts[f"generation_{generation}_idf_corpus_scoped"] = compare(
                observed_gen,
                expected_scores(query, visible(generation), average_length),
            )
            facts[f"generation_{generation}_idf_corpus_scoped_excluding_empty"] = (
                compare(
                    observed_gen,
                    expected_scores(
                        query,
                        [d for d in visible(generation) if d["tokens"]],
                        average_length,
                    ),
                )
            )
            observed_global = await sparse_scores(
                http, query, vocab, filter_=gen_filter, idf_corpus=None
            )
            expected_global = {
                k: v
                for k, v in expected_scores(query, DOCUMENTS, average_length).items()
                if k in {d["id"] for d in visible(generation)}
            }
            facts[f"generation_{generation}_idf_default_global"] = compare(
                observed_global, expected_global
            )

        # 7. Exact count with match-any on lexical_terms.
        count_body = {
            "exact": True,
            "filter": {
                "must": [
                    *generation_filter(1)["must"],  # type: ignore[misc]
                    {"key": "lexical_terms", "match": {"any": ["bm25", "rrf"]}},
                ]
            },
        }
        counted = await call(
            http, "POST", f"/collections/{COLLECTION}/points/count", count_body
        )
        facts["count_match_any_generation_1"] = {
            "observed": counted["result"]["count"],
            "expected": sum(
                1 for d in visible(1) if {"bm25", "rrf"} & set(d["tokens"])
            ),
            "body": count_body,
        }

        # 8. Batch query: dense and sparse in one call.
        batch_body = {
            "searches": [
                {"query": [1.0, 1.0, 1.0, 1.0], "using": "dense", "limit": 3},
                {
                    "query": sparse({"bm25": 1.0}, vocab),
                    "using": "scientific_bm25",
                    "limit": 3,
                },
            ]
        }
        batch = await call(
            http, "POST", f"/collections/{COLLECTION}/points/query/batch", batch_body
        )
        facts["batch_query"] = {"result_lists": len(batch["result"])}

        # 9. Retire two generation-1 points in generation 2 via set payload.
        await call(
            http,
            "POST",
            f"/collections/{COLLECTION}/points/payload?wait=true",
            {"payload": {"retired_generation": 2}, "points": [1, 2]},
        )
        counts = {}
        for generation in (1, 2):
            result = await call(
                http,
                "POST",
                f"/collections/{COLLECTION}/points/count",
                {"exact": True, "filter": generation_filter(generation)},
            )
            counts[generation] = result["result"]["count"]
        expected_counts = {}
        for generation in (1, 2):
            expected_counts[generation] = sum(
                1
                for doc in DOCUMENTS
                if doc["added"] <= generation
                and not (doc["id"] in {1, 2} and generation >= 2)
                and not ("retired" in doc and doc["retired"] <= generation)
            )
        facts["retirement_counts"] = {"observed": counts, "expected": expected_counts}

        # 10. Recommend on the dense vector.
        recommend = await call(
            http,
            "POST",
            f"/collections/{COLLECTION}/points/query",
            {
                "query": {"recommend": {"positive": [3]}},
                "using": "dense",
                "filter": {"must_not": [{"has_id": [3]}]},
                "limit": 3,
            },
        )
        facts["recommend"] = {"returned": len(recommend["result"]["points"])}

        # Retrieve preserves request order?
        retrieved = await call(
            http,
            "POST",
            f"/collections/{COLLECTION}/points",
            {"ids": [7, 3, 6], "with_payload": True, "with_vector": False},
        )
        facts["retrieve_order"] = [int(p["id"]) for p in retrieved["result"]]
        await http.delete(f"/collections/{COLLECTION}")
    return facts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:6340")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.url)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
