"""Unit tests for generation verification, publication and purge (P35-08)."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from research_platform.ingestion.generation_build import PassageInput
from research_platform.ingestion.generation_index import (
    GenerationMatch,
    GenerationQdrantCollection,
    passage_point_id,
)
from research_platform.ingestion.generation_publication import (
    REQUIRED_PASSAGE_FIELDS,
    publish_generation,
    purge_retired,
    verify_generation,
)
from research_platform.ingestion.generation_registry import (
    GenerationRecord,
    PublicationConflict,
)

CONFIGURATION_ID = "sha256:" + "a" * 64
COLLECTION_ID = uuid4()
SNAPSHOT_ID = uuid4()


def _input(evidence_id: str) -> PassageInput:
    return PassageInput(evidence_id, f"text {evidence_id}", {"paper_id": "W1"})


def _payload(item: PassageInput, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {field: None for field in REQUIRED_PASSAGE_FIELDS}
    payload.update(
        {
            "evidence_id": item.evidence_id,
            "paper_id": "W1",
            "text": item.text,
            "text_sha256": item.text_sha256,
            "index_configuration_id": CONFIGURATION_ID,
            "added_generation": 1,
        }
    )
    payload.update(overrides)
    return payload


def _record(generation: int, state: str = "building") -> GenerationRecord:
    return GenerationRecord(
        collection_id=COLLECTION_ID,
        configuration_id=CONFIGURATION_ID,
        generation=generation,
        snapshot_id=SNAPSHOT_ID,
        parent_generation=None if generation == 1 else generation - 1,
        manifest_sha256="b" * 64,
        state=state,  # type: ignore[arg-type]
        point_count=0,
        details={},
    )


class _Registry:
    def __init__(self, record: GenerationRecord, published: int | None = None) -> None:
        self.record = record
        self.verified: dict[str, object] | None = None
        self.failed: str | None = None
        self.published_generation = published
        self.publish_calls: list[tuple[int, int | None]] = []

    async def get(self, collection_id: UUID, configuration_id: str, generation: int):
        return self.record

    async def mark_verified(
        self, *_args: object, point_count: int, details: Mapping[str, object]
    ) -> None:
        self.verified = {"point_count": point_count, **details}

    async def mark_failed(self, *_args: object, reason: str) -> None:
        self.failed = reason

    async def published(self, collection_id: UUID, configuration_id: str):
        if self.published_generation is None:
            return None
        return _record(self.published_generation, "published")

    async def publish(
        self,
        collection_id: UUID,
        configuration_id: str,
        generation: int,
        *,
        expected_predecessor: int | None,
    ) -> None:
        self.publish_calls.append((generation, expected_predecessor))


class _Inputs:
    def __init__(self, items: Sequence[PassageInput]) -> None:
        self.items = tuple(items)

    async def load_passage_inputs(self, snapshot_id: UUID) -> tuple[PassageInput, ...]:
        return self.items


class _Members:
    def __init__(self, members: set[str]) -> None:
        self.members = frozenset(members)

    async def snapshot_member_ids(self, snapshot_id: UUID) -> frozenset[str]:
        return self.members


class _Passages:
    def __init__(
        self,
        payloads: Sequence[dict[str, object]],
        *,
        count: int | None = None,
        probe_score: float = 1.0,
    ) -> None:
        self.payloads = list(payloads)
        self.count_value = len(payloads) if count is None else count
        self.probe_score = probe_score
        self.deleted: list[Mapping[str, object]] = []
        self.probe_queue: list[dict[str, object]] = []

    async def scroll_payloads(
        self, *, filter_: Mapping[str, object], fields: Sequence[str]
    ):
        return tuple(self.payloads)

    async def count(self, filter_: Mapping[str, object]) -> int:
        return self.count_value

    async def retrieve(self, point_ids: Sequence[UUID], *, with_dense: bool = False):
        by_id = {
            passage_point_id(cast(str, p["evidence_id"]), CONFIGURATION_ID): p
            for p in self.payloads
        }
        found = [point_id for point_id in point_ids if point_id in by_id]
        self.probe_queue = [by_id[point_id] for point_id in found]
        return tuple(
            GenerationMatch(point_id, 0.0, by_id[point_id], dense=(1.0, 0.0))
            for point_id in found
        )

    async def query_dense(
        self, vector: Sequence[float], *, filter_: Mapping[str, object], limit: int
    ):
        return (GenerationMatch(uuid4(), self.probe_score, self.probe_queue.pop(0)),)

    async def delete_matching(self, filter_: Mapping[str, object]) -> None:
        self.deleted.append(filter_)


class _Papers:
    def __init__(self, indexed: Sequence[str]) -> None:
        self.indexed = indexed

    async def scroll_payloads(
        self, *, filter_: Mapping[str, object], fields: Sequence[str]
    ):
        return tuple({"paper_id": paper_id} for paper_id in self.indexed)


def _verify(
    payloads: Sequence[dict[str, object]],
    *,
    inputs: Sequence[PassageInput] | None = None,
    count: int | None = None,
    indexed: Sequence[str] = ("W1",),
    probe_score: float = 1.0,
) -> tuple[Any, _Registry]:
    registry = _Registry(_record(1))
    items = inputs if inputs is not None else [_input("e1"), _input("e2")]
    passages = _Passages(payloads, count=count, probe_score=probe_score)
    report = asyncio.run(
        verify_generation(
            registry=registry,
            inputs=_Inputs(items),
            papers_repository=_Members({"W1"}),
            passages=cast(GenerationQdrantCollection, passages),
            papers=cast(GenerationQdrantCollection, _Papers(indexed)),
            collection_id=COLLECTION_ID,
            configuration_id=CONFIGURATION_ID,
            generation=1,
            probe_count=1,
        )
    )
    return report, registry


def test_verification_passes_for_exact_match() -> None:
    items = [_input("e1"), _input("e2")]
    report, registry = _verify([_payload(item) for item in items])

    assert report.passed
    assert registry.verified is not None and registry.verified["point_count"] == 2
    assert registry.failed is None


def test_missing_point_fails() -> None:
    report, registry = _verify([_payload(_input("e1"))], count=1)
    assert not report.passed and report.missing_count == 1
    assert registry.failed == "verification_failed"


def test_unexpected_point_fails() -> None:
    items = [_input("e1"), _input("e2"), _input("e9")]
    report, _ = _verify([_payload(item) for item in items])
    assert not report.passed and report.unexpected_count == 1


def test_same_counts_with_wrong_ids_fails() -> None:
    report, registry = _verify([_payload(_input("e1")), _payload(_input("e3"))])
    assert report.observed_count == report.expected_count == 2
    assert not report.passed
    assert (report.missing_count, report.unexpected_count) == (1, 1)
    assert registry.verified is None


def test_hash_mismatch_fails() -> None:
    stale = _payload(_input("e2"), text="different text")
    report, _ = _verify([_payload(_input("e1")), stale])
    assert not report.passed and report.hash_mismatch_count == 1

    wrong_expected = _payload(
        _input("e2"),
        text="other",
        text_sha256=hashlib.sha256(b"other").hexdigest(),
    )
    report, _ = _verify([_payload(_input("e1")), wrong_expected])
    assert report.hash_mismatch_count == 1


def test_missing_payload_field_fails() -> None:
    incomplete = _payload(_input("e2"))
    del incomplete["source_spans"]
    report, _ = _verify([_payload(_input("e1")), incomplete])
    assert not report.passed and report.missing_payload_field_count == 1


def test_unindexed_member_paper_fails() -> None:
    items = [_input("e1"), _input("e2")]
    report, _ = _verify([_payload(item) for item in items], indexed=())
    assert not report.passed and report.unindexed_member_paper_count == 1


def test_probe_failure_fails() -> None:
    items = [_input("e1"), _input("e2")]
    report, _ = _verify([_payload(item) for item in items], probe_score=0.5)
    assert not report.passed and report.probe_failures == 1


def test_publish_requires_previous_generation_pointer() -> None:
    registry = _Registry(_record(3), published=1)
    with pytest.raises(PublicationConflict, match="must follow"):
        asyncio.run(publish_generation(registry, COLLECTION_ID, CONFIGURATION_ID, 3))
    asyncio.run(publish_generation(registry, COLLECTION_ID, CONFIGURATION_ID, 2))
    first = _Registry(_record(1))
    asyncio.run(publish_generation(first, COLLECTION_ID, CONFIGURATION_ID, 1))
    assert registry.publish_calls == [(2, 1)]
    assert first.publish_calls == [(1, None)]


class _Pool:
    def __init__(self, oldest_run: int | None) -> None:
        self.oldest_run = oldest_run

    def acquire(self) -> Any:
        pool = self

        class _Connection:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *_exc: object) -> None:
                return None

            async def fetchval(self, _sql: str) -> int | None:
                return pool.oldest_run

        return _Connection()


def test_purge_keeps_points_visible_to_pinned_runs() -> None:
    passages = _Passages([], count=4)
    count = asyncio.run(
        purge_retired(
            pool=cast(Any, _Pool(oldest_run=2)),
            registry=_Registry(_record(3), published=3),
            passages=cast(GenerationQdrantCollection, passages),
            collection_id=COLLECTION_ID,
            configuration_id=CONFIGURATION_ID,
            dry_run=False,
        )
    )
    assert count == 4
    assert passages.deleted == [
        {"must": [{"key": "retired_generation", "range": {"lte": 2}}]}
    ]


def test_purge_dry_run_deletes_nothing() -> None:
    passages = _Passages([], count=4)
    count = asyncio.run(
        purge_retired(
            pool=cast(Any, _Pool(oldest_run=None)),
            registry=_Registry(_record(3), published=3),
            passages=cast(GenerationQdrantCollection, passages),
            collection_id=COLLECTION_ID,
            configuration_id=CONFIGURATION_ID,
        )
    )
    assert count == 4 and passages.deleted == []
