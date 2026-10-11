"""The recording LLM client persists one record per model call."""

from __future__ import annotations

import dataclasses
from uuid import UUID

import pytest
from pydantic import BaseModel

from research_platform.llm.contracts import (
    ChatMessage,
    LLMUnavailable,
    StructuredCall,
    ToolCallRequest,
)
from research_platform.llm.recording import RecordingLLMClient
from research_platform.llm.scripted import ScriptedLLM, ScriptedReply
from research_platform.llm.types import CallKind, DecodingSettings, ModelIdentity
from research_platform.runs.contracts import ResearchMode, ResearchRequest
from research_platform.runs.memory import InMemoryRunStore

_IDENTITY = ModelIdentity(name="scripted", runtime="scripted", context_tokens=8192)
_MESSAGES = (ChatMessage("system", "rules"), ChatMessage("user", "question"))
_TOOLS = (
    {"type": "function", "function": {"name": "search_papers", "parameters": {}}},
    {"type": "function", "function": {"name": "get_paper", "parameters": {}}},
)


class Answer(BaseModel):
    value: str


async def _setup(
    replies: tuple[ScriptedReply, ...],
    *,
    store_payloads: bool = False,
    decoding: DecodingSettings | None = None,
) -> tuple[InMemoryRunStore, UUID, RecordingLLMClient]:
    store = InMemoryRunStore()
    run_id = await store.create_run(
        ResearchRequest(question="q x y", mode=ResearchMode.QUICK)
    )
    client = RecordingLLMClient(
        ScriptedLLM(replies, identity=_IDENTITY),
        sink=store,
        run_id=run_id,
        model_name="scripted",
        store_payloads=store_payloads,
        prompt_versions={"synthesize": "p3-synthesize-v2", "plan": "p3-plan-v1"},
        prompt_fingerprints={"synthesize": "f" * 64},
        decoding=decoding,
    )
    return store, run_id, client


def _structured() -> StructuredCall[Answer]:
    return StructuredCall(
        kind=CallKind.SYNTHESIZE,
        messages=_MESSAGES,
        output_model=Answer,
        think=True,
        max_output_tokens=None,
    )


@pytest.mark.anyio
async def test_successful_generate_is_recorded() -> None:
    store, run_id, client = await _setup(
        (ScriptedReply(kind=CallKind.SYNTHESIZE, content='{"value": "ok"}'),)
    )

    result = await client.generate(_structured())
    calls = await store.list_llm_calls(run_id)

    assert result.value.value == "ok"
    assert [call.ordinal for call in calls] == [1]
    record = calls[0].record
    assert record.kind is CallKind.SYNTHESIZE
    assert record.status == "succeeded"
    assert record.attempts == 1
    assert record.prompt_version == "p3-synthesize-v2"
    assert record.prompt_fingerprint == "f" * 64
    assert record.options["num_predict"] == -1
    assert record.options["think"] is True


@pytest.mark.anyio
async def test_payload_only_when_enabled() -> None:
    reply = (ScriptedReply(kind=CallKind.SYNTHESIZE, content='{"value": "ok"}'),)
    off_store, off_run, off_client = await _setup(reply)
    on_store, on_run, on_client = await _setup(reply, store_payloads=True)

    await off_client.generate(_structured())
    await on_client.generate(_structured())

    off = await off_store.list_llm_calls(off_run, include_payloads=True)
    on = await on_store.list_llm_calls(on_run, include_payloads=True)
    assert off[0].payload is None
    assert on[0].payload is not None
    assert on[0].payload.messages == _MESSAGES
    assert on[0].payload.output == '{"value": "ok"}'


@pytest.mark.anyio
async def test_failed_generate_is_recorded_and_reraised() -> None:
    store, run_id, client = await _setup(
        (ScriptedReply(kind=CallKind.SYNTHESIZE, error=LLMUnavailable("down")),),
        store_payloads=True,
    )

    with pytest.raises(LLMUnavailable):
        await client.generate(_structured())

    calls = await store.list_llm_calls(run_id, include_payloads=True)
    assert calls[0].record.status == "failed"
    assert calls[0].record.error_type == "LLMUnavailable"
    assert calls[0].record.attempts == 1
    assert calls[0].payload is not None
    assert calls[0].payload.output is None


@pytest.mark.anyio
async def test_call_tools_recorded_as_plan_with_tool_names() -> None:
    store, run_id, client = await _setup(
        (
            ScriptedReply(
                kind=CallKind.PLAN,
                tool_calls=({"function": {"name": "search_papers", "arguments": {}}},),
            ),
        ),
        store_payloads=True,
    )

    await client.call_tools(
        ToolCallRequest(messages=_MESSAGES, tools=_TOOLS, think=False)
    )

    calls = await store.list_llm_calls(run_id, include_payloads=True)
    assert calls[0].record.kind is CallKind.PLAN
    assert calls[0].record.prompt_version == "p3-plan-v1"
    assert calls[0].record.options["tools"] == ["search_papers", "get_paper"]
    assert calls[0].payload is not None
    assert "search_papers" in (calls[0].payload.output or "")


@pytest.mark.anyio
async def test_identity_delegates() -> None:
    _store, _run_id, client = await _setup(())

    assert await client.identity() == _IDENTITY


@pytest.mark.anyio
async def test_decoding_options_recorded() -> None:
    store, run_id, client = await _setup(
        (ScriptedReply(kind=CallKind.SYNTHESIZE, content='{"value": "ok"}'),),
        decoding=DecodingSettings(seed=7, context_tokens=4096, timeout_seconds=30),
    )

    await client.generate(_structured())

    options = (await store.list_llm_calls(run_id))[0].record.options
    assert options["seed"] == 7
    assert options["num_ctx"] == 4096
    assert options["temperature"] is None


@pytest.mark.anyio
async def test_sampling_options_are_recorded() -> None:
    store, run_id, client = await _setup(
        (ScriptedReply(kind=CallKind.SYNTHESIZE, content='{"value": "ok"}'),),
        decoding=DecodingSettings(
            seed=7,
            context_tokens=4096,
            timeout_seconds=30,
            temperature=1.0,
            top_k=20,
            top_p=0.95,
            presence_penalty=1.5,
        ),
    )

    await client.generate(_structured())

    options = (await store.list_llm_calls(run_id))[0].record.options
    assert (options["temperature"], options["top_k"]) == (1.0, 20)
    assert (options["top_p"], options["presence_penalty"]) == (0.95, 1.5)


@pytest.mark.anyio
async def test_recorded_seed_includes_the_call_seed_offset() -> None:
    store, run_id, client = await _setup(
        (ScriptedReply(kind=CallKind.SYNTHESIZE, content='{"value": "ok"}'),),
        decoding=DecodingSettings(seed=7, context_tokens=4096, timeout_seconds=30),
    )

    await client.generate(dataclasses.replace(_structured(), seed_offset=2))

    options = (await store.list_llm_calls(run_id))[0].record.options
    assert options["seed"] == 9
    assert options["seed_offset"] == 2
