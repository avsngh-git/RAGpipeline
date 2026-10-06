"""Generation-tagged Qdrant collections for passages and papers (ADR-0022, ADR-0023).

Request shapes follow the P35-02 spike report (docs/research/phase-3.5-qdrant-spike.md).
Every sparse query sends the IDF corpus filter so that Qdrant's Lucene IDF counts the
same documents as BM25S.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast
from urllib.parse import quote
from uuid import UUID, uuid5

import httpx

from research_platform.ingestion.indexing import (
    IndexConfiguration,
    IndexConfigurationMismatch,
    IndexDistance,
)

GENERATION_PAYLOAD_REVISION = "generation-content-payload-v1"
DENSE_VECTOR = "dense"
SPARSE_VECTOR = "scientific_bm25"
CollectionRole = Literal["passages", "papers"]

_PASSAGE_NAMESPACE = UUID("6f1d3c52-0d0e-4b7a-9a43-2f3a35d1c0a1")
_PAPER_NAMESPACE = UUID("b8e0f2a4-5c71-4a39-8e16-7d4a35c2e9f3")
_COLLECTION_NAME = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DISTANCES = {"Cosine", "Dot", "Euclid", "Manhattan"}
_SCROLL_PAGE = 256
_PAYLOAD_INDEXES: Mapping[CollectionRole, tuple[tuple[str, str], ...]] = {
    "passages": (
        ("paper_id", "keyword"),
        ("publication_year", "integer"),
        ("evidence_kind", "keyword"),
        ("document_version_kind", "keyword"),
        ("added_generation", "integer"),
        ("retired_generation", "integer"),
    ),
    "papers": (
        ("paper_id", "keyword"),
        ("publication_year", "integer"),
        ("indexed_generation", "integer"),
        ("catalog_status", "keyword"),
    ),
}


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _require_finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(value)


@dataclass(frozen=True)
class SparseLexicalSettings:
    """Analyzer, vocabulary and BM25 parameters that determine sparse weights."""

    analyzer: str
    analyzer_revision: str
    vocabulary_id: str
    k1: float
    b: float
    evidence_average_length: float
    paper_average_length: float

    def __post_init__(self) -> None:
        for name in ("analyzer", "analyzer_revision", "vocabulary_id"):
            _require_text(getattr(self, name), name)
        if _require_finite(self.k1, "k1") <= 0:
            raise ValueError("k1 must be positive")
        if not 0 <= _require_finite(self.b, "b") <= 1:
            raise ValueError("b must be between 0 and 1")
        for name in ("evidence_average_length", "paper_average_length"):
            if _require_finite(getattr(self, name), name) <= 0:
                raise ValueError(f"{name} must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "analyzer": self.analyzer,
            "analyzer_revision": self.analyzer_revision,
            "vocabulary_id": self.vocabulary_id,
            "k1": self.k1,
            "b": self.b,
            "evidence_average_length": self.evidence_average_length,
            "paper_average_length": self.paper_average_length,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> SparseLexicalSettings:
        expected = {
            "analyzer",
            "analyzer_revision",
            "vocabulary_id",
            "k1",
            "b",
            "evidence_average_length",
            "paper_average_length",
        }
        if set(data) != expected:
            raise ValueError("unsupported lexical settings fields")
        return cls(
            analyzer=cast(str, data["analyzer"]),
            analyzer_revision=cast(str, data["analyzer_revision"]),
            vocabulary_id=cast(str, data["vocabulary_id"]),
            k1=cast(float, data["k1"]),
            b=cast(float, data["b"]),
            evidence_average_length=cast(float, data["evidence_average_length"]),
            paper_average_length=cast(float, data["paper_average_length"]),
        )


@dataclass(frozen=True)
class GenerationIndexConfiguration:
    """All choices that change the meaning or shape of generation collections."""

    passages_collection: str
    papers_collection: str
    embedding_model: str
    embedding_revision: str
    preprocessing_revision: str
    vector_size: int
    distance: IndexDistance
    batch_size: int
    maximum_input_tokens: int
    payload_revision: str = GENERATION_PAYLOAD_REVISION
    lexical: SparseLexicalSettings | None = None

    def __post_init__(self) -> None:
        for name in (
            "passages_collection",
            "papers_collection",
            "embedding_model",
            "embedding_revision",
            "preprocessing_revision",
            "payload_revision",
        ):
            _require_text(getattr(self, name), name)
        for name in ("passages_collection", "papers_collection"):
            if not _COLLECTION_NAME.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} contains unsupported characters")
        if self.passages_collection == self.papers_collection:
            raise ValueError("passages and papers need separate collections")
        for name in ("vector_size", "batch_size", "maximum_input_tokens"):
            _require_positive_int(getattr(self, name), name)
        if self.distance not in _DISTANCES:
            raise ValueError("unsupported Qdrant distance metric")
        if self.lexical is not None and not isinstance(
            self.lexical, SparseLexicalSettings
        ):
            raise ValueError("lexical must be SparseLexicalSettings or null")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "passages_collection": self.passages_collection,
            "papers_collection": self.papers_collection,
            "embedding_model": self.embedding_model,
            "embedding_revision": self.embedding_revision,
            "preprocessing_revision": self.preprocessing_revision,
            "vector_size": self.vector_size,
            "distance": self.distance,
            "batch_size": self.batch_size,
            "maximum_input_tokens": self.maximum_input_tokens,
            "payload_revision": self.payload_revision,
            "lexical": None if self.lexical is None else self.lexical.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> GenerationIndexConfiguration:
        expected = {
            "schema_version",
            "passages_collection",
            "papers_collection",
            "embedding_model",
            "embedding_revision",
            "preprocessing_revision",
            "vector_size",
            "distance",
            "batch_size",
            "maximum_input_tokens",
            "payload_revision",
            "lexical",
        }
        if set(data) != expected or data.get("schema_version") != 2:
            raise ValueError("unsupported generation configuration fields or version")
        lexical = data["lexical"]
        if lexical is not None and not isinstance(lexical, Mapping):
            raise ValueError("lexical must be an object or null")
        return cls(
            passages_collection=cast(str, data["passages_collection"]),
            papers_collection=cast(str, data["papers_collection"]),
            embedding_model=cast(str, data["embedding_model"]),
            embedding_revision=cast(str, data["embedding_revision"]),
            preprocessing_revision=cast(str, data["preprocessing_revision"]),
            vector_size=cast(int, data["vector_size"]),
            distance=cast(IndexDistance, data["distance"]),
            batch_size=cast(int, data["batch_size"]),
            maximum_input_tokens=cast(int, data["maximum_input_tokens"]),
            payload_revision=cast(str, data["payload_revision"]),
            lexical=None
            if lexical is None
            else SparseLexicalSettings.from_dict(lexical),
        )

    @property
    def configuration_id(self) -> str:
        canonical = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def dense_configuration(self) -> IndexConfiguration:
        """The dense model identity, in the form the existing embedders accept."""
        return IndexConfiguration(
            collection_name=self.passages_collection,
            embedding_model=self.embedding_model,
            embedding_revision=self.embedding_revision,
            preprocessing_revision=self.preprocessing_revision,
            vector_size=self.vector_size,
            distance=self.distance,
            batch_size=self.batch_size,
            maximum_input_tokens=self.maximum_input_tokens,
        )


@dataclass(frozen=True)
class SparseVector:
    """Sorted term IDs with positive weights; an empty vector is allowed."""

    indices: tuple[int, ...]
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.indices) != len(self.values):
            raise ValueError("sparse indices and values must have the same length")
        previous = -1
        for index in self.indices:
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise ValueError("sparse indices must be non-negative integers")
            if index <= previous:
                raise ValueError("sparse indices must be strictly increasing")
            previous = index
        for value in self.values:
            if _require_finite(value, "sparse value") <= 0:
                raise ValueError("sparse values must be positive")

    def to_json(self) -> dict[str, list[int] | list[float]]:
        return {"indices": list(self.indices), "values": list(self.values)}


@dataclass(frozen=True)
class GenerationPoint:
    point_id: UUID
    dense: Sequence[float]
    sparse: SparseVector | None
    payload: Mapping[str, object]


@dataclass(frozen=True)
class GenerationMatch:
    point_id: UUID
    score: float
    payload: Mapping[str, object]
    dense: tuple[float, ...] | None = None


def passage_point_id(evidence_id: str, configuration_id: str) -> UUID:
    """Stable passage point identity, shared by every generation of a configuration."""
    _require_text(evidence_id, "evidence_id")
    _require_text(configuration_id, "configuration_id")
    return uuid5(_PASSAGE_NAMESPACE, f"{configuration_id}:{evidence_id}")


def paper_point_id(paper_id: str, configuration_id: str) -> UUID:
    """Stable paper point identity for one configuration."""
    _require_text(paper_id, "paper_id")
    _require_text(configuration_id, "configuration_id")
    return uuid5(_PAPER_NAMESPACE, f"{configuration_id}:{paper_id}")


def generation_filter(generation: int) -> dict[str, object]:
    """Points visible in a generation: added by it and not retired at or before it."""
    _require_positive_int(generation, "generation")
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


def indexed_paper_filter(generation: int) -> dict[str, object]:
    """Papers with ingested evidence in a generation; metadata-only papers never match."""
    _require_positive_int(generation, "generation")
    return {"must": [{"key": "indexed_generation", "range": {"lte": generation}}]}


def with_conditions(
    filter_: Mapping[str, object], conditions: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Return a copy of ``filter_`` with extra conditions appended to ``must``."""
    combined = dict(filter_)
    must = combined.get("must", [])
    if not isinstance(must, list):
        raise ValueError("filter must clause must be a list")
    combined["must"] = [*must, *(dict(condition) for condition in conditions)]
    return combined


class GenerationQdrantCollection:
    """Small REST adapter for one generation-tagged passages or papers collection."""

    def __init__(
        self,
        configuration: GenerationIndexConfiguration,
        role: CollectionRole,
        http: httpx.AsyncClient,
    ) -> None:
        if role not in _PAYLOAD_INDEXES:
            raise ValueError("role must be passages or papers")
        self.configuration = configuration
        self.role = role
        self._http = http
        self._url = "/collections/" + quote(self.name, safe="")

    @property
    def name(self) -> str:
        if self.role == "passages":
            return self.configuration.passages_collection
        return self.configuration.papers_collection

    async def exists(self) -> bool:
        response = await self._http.get(self._url)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    async def ensure_collection(self) -> None:
        response = await self._http.get(self._url)
        if response.status_code == 404:
            body: dict[str, object] = {
                "vectors": {
                    DENSE_VECTOR: {
                        "size": self.configuration.vector_size,
                        "distance": self.configuration.distance,
                    }
                }
            }
            if self.configuration.lexical is not None:
                body["sparse_vectors"] = {SPARSE_VECTOR: {"modifier": "idf"}}
            created = await self._http.put(self._url, json=body)
            if created.status_code not in {200, 409}:
                created.raise_for_status()
            response = await self._http.get(self._url)
        response.raise_for_status()
        params = _dig(response.json(), "result", "config", "params")
        vectors = params.get("vectors") if isinstance(params, Mapping) else None
        dense = vectors.get(DENSE_VECTOR) if isinstance(vectors, Mapping) else None
        if (
            not isinstance(vectors, Mapping)
            or set(vectors) != {DENSE_VECTOR}
            or not isinstance(dense, Mapping)
            or dense.get("size") != self.configuration.vector_size
            or dense.get("distance") != self.configuration.distance
        ):
            raise IndexConfigurationMismatch(
                "Qdrant collection dense vector differs from the configuration"
            )
        sparse = params.get("sparse_vectors") if isinstance(params, Mapping) else None
        if self.configuration.lexical is None:
            if sparse:
                raise IndexConfigurationMismatch(
                    "Qdrant collection has sparse vectors the configuration lacks"
                )
        elif (
            not isinstance(sparse, Mapping)
            or set(sparse) != {SPARSE_VECTOR}
            or not isinstance(sparse[SPARSE_VECTOR], Mapping)
            or sparse[SPARSE_VECTOR].get("modifier") != "idf"
        ):
            raise IndexConfigurationMismatch(
                "Qdrant collection sparse vector differs from the configuration"
            )

    async def ensure_payload_indexes(self) -> None:
        schemas = list(_PAYLOAD_INDEXES[self.role])
        if self.configuration.lexical is not None:
            schemas.append(("lexical_terms", "keyword"))
        for field_name, field_schema in schemas:
            response = await self._http.put(
                f"{self._url}/index",
                params={"wait": "true"},
                json={"field_name": field_name, "field_schema": field_schema},
            )
            response.raise_for_status()

    async def upsert(self, points: Sequence[GenerationPoint]) -> int:
        if len(points) > self.configuration.batch_size:
            raise ValueError("Qdrant upsert exceeds the configured batch size")
        if not points:
            return 0
        if len({point.point_id for point in points}) != len(points):
            raise ValueError("an upsert batch cannot repeat point identities")
        serialized: list[dict[str, object]] = []
        for point in points:
            vector: dict[str, object] = {DENSE_VECTOR: self._dense(point.dense)}
            if point.sparse is not None:
                if self.configuration.lexical is None:
                    raise ValueError("sparse vectors require lexical settings")
                vector[SPARSE_VECTOR] = point.sparse.to_json()
            elif self.configuration.lexical is not None:
                raise ValueError(
                    "lexical collections require a sparse vector per point"
                )
            serialized.append(
                {
                    "id": str(point.point_id),
                    "vector": vector,
                    "payload": dict(point.payload),
                }
            )
        response = await self._http.put(
            f"{self._url}/points", params={"wait": "true"}, json={"points": serialized}
        )
        response.raise_for_status()
        return len(serialized)

    async def set_payload(
        self, point_ids: Sequence[UUID], payload: Mapping[str, object]
    ) -> None:
        if not point_ids:
            return
        response = await self._http.post(
            f"{self._url}/points/payload",
            params={"wait": "true"},
            json={"payload": dict(payload), "points": [str(i) for i in point_ids]},
        )
        response.raise_for_status()

    async def delete(self, point_ids: Sequence[UUID]) -> None:
        if not point_ids:
            return
        response = await self._http.post(
            f"{self._url}/points/delete",
            params={"wait": "true"},
            json={"points": [str(i) for i in point_ids]},
        )
        response.raise_for_status()

    async def delete_matching(self, filter_: Mapping[str, object]) -> None:
        """Delete every point matching a filter; an empty filter is refused."""
        if not filter_:
            raise ValueError("refusing to delete without a filter")
        response = await self._http.post(
            f"{self._url}/points/delete",
            params={"wait": "true"},
            json={"filter": dict(filter_)},
        )
        response.raise_for_status()

    async def count(self, filter_: Mapping[str, object]) -> int:
        response = await self._http.post(
            f"{self._url}/points/count", json={"exact": True, "filter": dict(filter_)}
        )
        response.raise_for_status()
        count = _dig(response.json(), "result", "count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise RuntimeError("Qdrant returned an invalid count")
        return count

    async def query_dense(
        self,
        vector: Sequence[float],
        *,
        filter_: Mapping[str, object],
        limit: int,
        exact: bool = False,
    ) -> tuple[GenerationMatch, ...]:
        """Nearest dense neighbours; ``exact`` scans instead of using the HNSW graph."""
        _require_positive_int(limit, "limit")
        body: dict[str, object] = {
            "query": self._dense(vector),
            "using": DENSE_VECTOR,
            "filter": dict(filter_),
            "limit": limit,
        }
        if exact:
            body["params"] = {"exact": True}
        return await self._query(body)

    async def query_sparse(
        self,
        vector: SparseVector,
        *,
        filter_: Mapping[str, object],
        idf_filter: Mapping[str, object],
        limit: int,
    ) -> tuple[GenerationMatch, ...]:
        if self.configuration.lexical is None:
            raise ValueError("sparse queries require lexical settings")
        _require_positive_int(limit, "limit")
        if not vector.indices:
            return ()
        return await self._query(
            {
                "query": vector.to_json(),
                "using": SPARSE_VECTOR,
                "filter": dict(filter_),
                "params": {"idf": {"corpus": dict(idf_filter)}},
                "limit": limit,
            }
        )

    async def recommend(
        self,
        positive: UUID,
        *,
        filter_: Mapping[str, object],
        limit: int,
    ) -> tuple[GenerationMatch, ...]:
        _require_positive_int(limit, "limit")
        excluded = {"must_not": [{"has_id": [str(positive)]}]}
        combined = dict(filter_)
        combined["must_not"] = [
            *cast(list[object], combined.get("must_not", [])),
            *excluded["must_not"],
        ]
        return await self._query(
            {
                "query": {"recommend": {"positive": [str(positive)]}},
                "using": DENSE_VECTOR,
                "filter": combined,
                "limit": limit,
            }
        )

    async def retrieve(
        self, point_ids: Sequence[UUID], *, with_dense: bool = False
    ) -> tuple[GenerationMatch, ...]:
        """Return existing points in the requested order; missing points are omitted."""
        if not point_ids:
            return ()
        response = await self._http.post(
            f"{self._url}/points",
            json={
                "ids": [str(i) for i in point_ids],
                "with_payload": True,
                "with_vector": [DENSE_VECTOR] if with_dense else False,
            },
        )
        response.raise_for_status()
        raw = _dig(response.json(), "result")
        if not isinstance(raw, list):
            raise RuntimeError("Qdrant returned an invalid retrieve response")
        by_id = {match.point_id: match for match in map(_match, raw)}
        return tuple(by_id[i] for i in point_ids if i in by_id)

    async def scroll_payloads(
        self, *, filter_: Mapping[str, object], fields: Sequence[str]
    ) -> tuple[Mapping[str, object], ...]:
        """Read the requested payload fields of every matching point, without vectors."""
        if not fields or any(not isinstance(f, str) or not f for f in fields):
            raise ValueError("fields must name at least one payload field")
        payloads: list[Mapping[str, object]] = []
        offset: object = None
        while True:
            body: dict[str, object] = {
                "filter": dict(filter_),
                "limit": _SCROLL_PAGE,
                "with_payload": list(fields),
                "with_vector": False,
            }
            if offset is not None:
                body["offset"] = offset
            response = await self._http.post(f"{self._url}/points/scroll", json=body)
            response.raise_for_status()
            result = _dig(response.json(), "result")
            if not isinstance(result, Mapping) or not isinstance(
                points := result.get("points"), list
            ):
                raise RuntimeError("Qdrant returned an invalid scroll response")
            payloads.extend(_match(point).payload for point in points)
            offset = result.get("next_page_offset")
            if offset is None or not points:
                return tuple(payloads)

    def _dense(self, vector: Sequence[float]) -> list[float]:
        if len(vector) != self.configuration.vector_size:
            raise ValueError(
                f"dense vector must contain exactly {self.configuration.vector_size} values"
            )
        return [_require_finite(value, "dense value") for value in vector]

    async def _query(self, body: dict[str, object]) -> tuple[GenerationMatch, ...]:
        body.update({"with_payload": True, "with_vector": False})
        response = await self._http.post(f"{self._url}/points/query", json=body)
        response.raise_for_status()
        points = _dig(response.json(), "result", "points")
        if not isinstance(points, list):
            raise RuntimeError("Qdrant returned an invalid query response")
        return tuple(_match(point) for point in points)


def _dig(value: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(value, Mapping):
            raise RuntimeError("Qdrant returned an unexpected response shape")
        value = value.get(key)
    return value


def _match(raw: object) -> GenerationMatch:
    if not isinstance(raw, Mapping):
        raise RuntimeError("Qdrant returned a malformed point")
    payload = raw.get("payload")
    score = raw.get("score", 0.0)
    if (
        not isinstance(payload, Mapping)
        or isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
    ):
        raise RuntimeError("Qdrant returned a malformed point")
    try:
        point_id = UUID(str(raw.get("id")))
    except ValueError:
        raise RuntimeError("Qdrant returned a point without a UUID") from None
    dense: tuple[float, ...] | None = None
    vector = raw.get("vector")
    if isinstance(vector, Mapping) and isinstance(vector.get(DENSE_VECTOR), list):
        dense = tuple(float(value) for value in vector[DENSE_VECTOR])
    return GenerationMatch(
        point_id=point_id, score=float(score), payload=dict(payload), dense=dense
    )
