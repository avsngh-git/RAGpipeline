"""In-memory store coverage for Phase 4 run records."""

from __future__ import annotations

from uuid import uuid4

import pytest

from research_platform.llm.contracts import ChatMessage
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimVerdict,
    DraftClaimOutcome,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunProvenance,
    RunUsage,
    SynthesisSummary,
    configuration_id,
)
from research_platform.runs.llm_records import LLMCallPayload, LLMCallRecord
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.repository import ConfigurationNotFound, RunNotFound

_PAYLOAD: dict[str, object] = {
    "provenance_version": 2,
    "mode": "quick",
    "budgets": {"max_active_seconds": 1800.0, "max_tool_calls": 12},
    "decoding": None,
    "prompt_versions": {"system": "p3-system-v1"},
    "filters": {"year_from": 2020, "year_to": None},
    "list": [1, 2.5, "three"],
}


@pytest.mark.anyio
async def test_memory_round_trip_preserves_configuration_id() -> None:
    store = InMemoryRunStore()
    expected = configuration_id(_PAYLOAD)

    await store.save_run_configuration(expected, _PAYLOAD, provenance_version=2)
    loaded = await store.load_run_configuration(expected)

    assert loaded == _PAYLOAD
    assert configuration_id(loaded) == expected


@pytest.mark.anyio
async def test_memory_save_is_idempotent() -> None:
    store = InMemoryRunStore()
    expected = configuration_id(_PAYLOAD)

    await store.save_run_configuration(expected, _PAYLOAD, provenance_version=2)
    await store.save_run_configuration(expected, _PAYLOAD, provenance_version=2)

    assert await store.load_run_configuration(expected) == _PAYLOAD


@pytest.mark.anyio
async def test_memory_save_rejects_wrong_id() -> None:
    store = InMemoryRunStore()

    with pytest.raises(ValueError, match="does not match"):
        await store.save_run_configuration(
            "sha256:" + "0" * 64, _PAYLOAD, provenance_version=2
        )


@pytest.mark.anyio
async def test_memory_load_missing_raises() -> None:
    store = InMemoryRunStore()

    with pytest.raises(ConfigurationNotFound):
        await store.load_run_configuration("sha256:" + "1" * 64)


@pytest.mark.anyio
async def test_memory_loaded_configuration_is_a_copy() -> None:
    store = InMemoryRunStore()
    expected = configuration_id(_PAYLOAD)
    await store.save_run_configuration(expected, _PAYLOAD, provenance_version=2)

    loaded = await store.load_run_configuration(expected)
    loaded["mode"] = "changed"

    assert (await store.load_run_configuration(expected))["mode"] == "quick"


def _call(kind: CallKind = CallKind.PLAN) -> LLMCallRecord:
    return LLMCallRecord(
        kind=kind,
        status="succeeded",
        model_name="scripted",
        think=False,
        attempts=1,
        duration_ms=3.0,
        options={"seed": 7},
    )


async def _run(store: InMemoryRunStore):  # type: ignore[no-untyped-def]
    return await store.create_run(
        ResearchRequest(question="what helps", mode=ResearchMode.QUICK)
    )


@pytest.mark.anyio
async def test_memory_llm_calls_number_from_one() -> None:
    store = InMemoryRunStore()
    run_id = await _run(store)

    first = await store.append_llm_call(run_id, _call())
    second = await store.append_llm_call(run_id, _call(CallKind.SYNTHESIZE))
    calls = await store.list_llm_calls(run_id)

    assert (first, second) == (1, 2)
    assert [call.record.kind for call in calls] == [CallKind.PLAN, CallKind.SYNTHESIZE]


@pytest.mark.anyio
async def test_memory_payload_round_trip_and_hidden_unless_requested() -> None:
    store = InMemoryRunStore()
    run_id = await _run(store)
    payload = LLMCallPayload(
        messages=(ChatMessage("system", "rules"), ChatMessage("user", "question")),
        output='{"answer": "x"}',
        thinking="because",
    )

    await store.append_llm_call(run_id, _call(), payload)

    assert (await store.list_llm_calls(run_id))[0].payload is None
    stored = (await store.list_llm_calls(run_id, include_payloads=True))[0]
    assert stored.payload == payload


@pytest.mark.anyio
async def test_memory_append_for_unknown_run_raises() -> None:
    with pytest.raises(RunNotFound):
        await InMemoryRunStore().append_llm_call(uuid4(), _call())


_DRAFTS = (
    DraftClaimOutcome(
        ordinal=1,
        handle="E1",
        quote="a quote",
        text="a claim",
        verdict=ClaimVerdict.KEPT,
        chunk_id="chunk-1",
        paper_id="W1",
    ),
    DraftClaimOutcome(
        ordinal=2,
        handle="E7",
        quote="other",
        text="other claim",
        verdict=ClaimVerdict.FAILED_CHECKS,
        failed_checks=("quote_found", "numbers_from_quote"),
    ),
)
_SUMMARY = SynthesisSummary(
    model_declared_insufficient=False,
    relevant_handles=("E1",),
    packed_handles=("E1", "E7"),
    omitted_handles=("E9",),
    drafted=2,
)


@pytest.mark.anyio
async def test_memory_store_persists_drafts_and_synthesis() -> None:
    store = InMemoryRunStore()
    run_id = await _run(store)
    await store.mark_running(
        run_id,
        provenance=RunProvenance(
            snapshot_id=uuid4(),
            retrieval_profile_id="sha256:" + "a" * 64,
            configuration_id="sha256:" + "b" * 64,
            code_revision="test",
            model=ModelIdentity(name="m", runtime="scripted", context_tokens=8192),
            thinking={},
            prompt_versions={},
            budgets=RunBudgets(),
            trace_id="t",
        ),
    )

    await store.complete_run(
        run_id,
        answer="No supported claims.",
        outcome=AnswerOutcome.INSUFFICIENT_EVIDENCE,
        claims=(),
        usage=RunUsage(),
        drafts=_DRAFTS,
        synthesis=_SUMMARY,
    )

    assert await store.list_draft_claims(run_id) == _DRAFTS
    assert await store.get_synthesis_summary(run_id) == _SUMMARY
