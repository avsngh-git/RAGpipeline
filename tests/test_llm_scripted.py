"""Offline behavior for the scripted model client."""

import asyncio

import pytest
from pydantic import BaseModel

from research_platform.agents.tool_schemas import research_tool_definitions
from research_platform.llm.contracts import (
    ChatMessage,
    LLMInvalidOutput,
    LLMUnavailable,
    StructuredCall,
    ToolCallRequest,
)
from research_platform.llm.scripted import ScriptedLLM, ScriptedReply
from research_platform.llm.types import CallKind


class _Answer(BaseModel):
    answer: str


def _call(kind: CallKind = CallKind.PLAN) -> StructuredCall[_Answer]:
    return StructuredCall(
        kind=kind,
        messages=(ChatMessage(role="user", content="Answer briefly."),),
        output_model=_Answer,
        think=False,
    )


def test_returns_validated_reply_and_records_call() -> None:
    client = ScriptedLLM(
        [ScriptedReply(kind=CallKind.PLAN, content='{"answer":"ready"}')]
    )
    call = _call()

    result = asyncio.run(client.generate(call))

    assert result.value == _Answer(answer="ready")
    assert result.raw_content == '{"answer":"ready"}'
    assert result.thinking is None
    assert result.prompt_tokens is None
    assert result.output_tokens is None
    assert result.duration_ms == 0.0
    assert result.attempts == 1
    assert client.calls == [call]
    assert client.remaining == 0


def test_kind_mismatch_raises_assertion() -> None:
    client = ScriptedLLM(
        [ScriptedReply(kind=CallKind.EVALUATE, content='{"answer":"ready"}')]
    )

    with pytest.raises(AssertionError, match="expected plan, actual evaluate"):
        asyncio.run(client.generate(_call()))


def test_exhausted_script_raises_assertion() -> None:
    client = ScriptedLLM([])

    with pytest.raises(AssertionError, match="expected plan, actual <none>"):
        asyncio.run(client.generate(_call()))


def test_scripted_error_is_raised() -> None:
    error = LLMUnavailable("model is offline")
    client = ScriptedLLM([ScriptedReply(kind=CallKind.PLAN, error=error)])

    with pytest.raises(LLMUnavailable, match="model is offline") as raised:
        asyncio.run(client.generate(_call()))

    assert raised.value is error


def test_invalid_content_raises_invalid_output() -> None:
    content = '{"answer":7}'
    client = ScriptedLLM([ScriptedReply(kind=CallKind.PLAN, content=content)])

    with pytest.raises(LLMInvalidOutput) as raised:
        asyncio.run(client.generate(_call()))

    assert raised.value.attempts == 1
    assert raised.value.content_preview == content


def test_default_identity_and_reply_exclusivity() -> None:
    client = ScriptedLLM([])
    identity = asyncio.run(client.identity())

    assert identity.name == "scripted"
    assert identity.runtime == "scripted"
    assert identity.context_tokens == 16384
    with pytest.raises(ValueError, match="exactly one"):
        ScriptedReply(kind=CallKind.PLAN)
    with pytest.raises(ValueError, match="exactly one"):
        ScriptedReply(kind=CallKind.PLAN, content="{}", error=LLMUnavailable())


def test_scripted_tool_calls() -> None:
    call = ToolCallRequest(
        messages=(ChatMessage(role="user", content="Search."),),
        tools=tuple(research_tool_definitions()),
        think=True,
    )
    tool_calls = (
        {"function": {"name": "search_papers", "arguments": {"query": "RAG"}}},
    )
    client = ScriptedLLM([ScriptedReply(kind=CallKind.PLAN, tool_calls=tool_calls)])

    result = asyncio.run(client.call_tools(call))

    assert result.calls == tool_calls
    assert result.thinking is None
    assert result.attempts == 1
    assert client.tool_requests == [call]


def test_tool_call_kind_mismatch_raises() -> None:
    call = ToolCallRequest(
        messages=(ChatMessage(role="user", content="Search."),),
        tools=tuple(research_tool_definitions()),
        think=True,
    )
    client = ScriptedLLM(
        [
            ScriptedReply(
                kind=CallKind.EVALUATE,
                tool_calls=({"function": {"name": "get_paper"}},),
            )
        ]
    )

    with pytest.raises(AssertionError, match="expected plan, actual evaluate"):
        asyncio.run(client.call_tools(call))
