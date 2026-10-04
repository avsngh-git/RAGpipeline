"""Offline tests for the Ollama model adapter."""

import asyncio
import json
import logging

import httpx
import pytest
from pydantic import BaseModel

from research_platform.agents.tool_schemas import research_tool_definitions
from research_platform.llm.contracts import (
    ChatMessage,
    LLMInvalidOutput,
    LLMRequestRejected,
    LLMTimeout,
    LLMUnavailable,
    StructuredCall,
    ToolCallRequest,
)
from research_platform.llm.ollama import OllamaClient
from research_platform.llm.types import CallKind


class _Answer(BaseModel):
    answer: str


def _call(
    *,
    content: str = "Write an answer.",
    max_repair_attempts: int = 2,
    think: bool = True,
) -> StructuredCall[_Answer]:
    return StructuredCall(
        kind=CallKind.PLAN,
        messages=(ChatMessage(role="user", content=content),),
        output_model=_Answer,
        think=think,
        max_repair_attempts=max_repair_attempts,
    )


def _adapter(http: httpx.AsyncClient) -> OllamaClient:
    return OllamaClient(
        http,
        base_url="http://ollama.test/",
        model="local-model:v1",
        context_tokens=8192,
        timeout_seconds=12.5,
        seed=17,
    )


def _tool_request(*, max_repair_attempts: int = 2) -> ToolCallRequest:
    return ToolCallRequest(
        messages=(ChatMessage(role="user", content="Find papers."),),
        tools=tuple(research_tool_definitions()),
        think=True,
        max_repair_attempts=max_repair_attempts,
    )


def test_request_body_has_schema_think_and_options() -> None:
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"message": {"content": '{"answer":"ok"}'}, "eval_count": 3},
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            await _adapter(http).generate(_call())

    asyncio.run(exercise())

    request = captured[0]
    payload = json.loads(request.read())
    assert request.url == "http://ollama.test/api/chat"
    assert payload["model"] == "local-model:v1"
    assert payload["messages"] == [{"role": "user", "content": "Write an answer."}]
    assert payload["stream"] is False
    assert payload["format"] == _Answer.model_json_schema()
    assert payload["think"] is True
    assert payload["options"] == {
        "num_ctx": 8192,
        "num_predict": 2048,
        "seed": 17,
    }
    assert request.extensions["timeout"]["write"] == 12.5


def test_uncapped_call_sends_no_output_limit() -> None:
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"message": {"content": '{"answer":"ok"}'}})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            call = StructuredCall(
                kind=CallKind.SYNTHESIZE,
                messages=(ChatMessage(role="user", content="Write an answer."),),
                output_model=_Answer,
                think=True,
                max_output_tokens=None,
            )
            await _adapter(http).generate(call)

    asyncio.run(exercise())

    assert json.loads(captured[0].read())["options"]["num_predict"] == -1


def test_valid_reply_returns_model_and_token_counts() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {"content": '{"answer":"ready"}', "thinking": "reason"},
                "prompt_eval_count": 14,
                "eval_count": 5,
            },
        )

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            return await _adapter(http).generate(_call())

    result = asyncio.run(exercise())

    assert result.value == _Answer(answer="ready")
    assert result.raw_content == '{"answer":"ready"}'
    assert result.thinking == "reason"
    assert result.prompt_tokens == 14
    assert result.output_tokens == 5
    assert result.duration_ms >= 0
    assert result.attempts == 1


def test_invalid_reply_is_repaired_once_then_succeeds() -> None:
    requests: list[dict[str, object]] = []
    replies = iter(["not json", '{"answer":"repaired"}'])

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return httpx.Response(
            200,
            json={"message": {"content": next(replies)}},
        )

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            return await _adapter(http).generate(_call(max_repair_attempts=1))

    result = asyncio.run(exercise())

    assert result.value == _Answer(answer="repaired")
    assert result.attempts == 2
    assert len(requests) == 2
    messages = requests[1]["messages"]
    assert messages[0] == {"role": "user", "content": "Write an answer."}
    assert messages[1] == {"role": "assistant", "content": "not json"}
    repair_prompt = messages[2]["content"]
    assert isinstance(repair_prompt, str)
    assert "did not match the required JSON schema" in repair_prompt


def test_invalid_reply_exhausts_repairs_and_raises_invalid_output() -> None:
    request_count = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"message": {"content": "invalid"}})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            await _adapter(http).generate(_call())

    with pytest.raises(LLMInvalidOutput) as raised:
        asyncio.run(exercise())

    assert request_count == 3
    assert raised.value.attempts == 3
    assert raised.value.content_preview == "invalid"


def test_call_tools_sends_tools_without_format() -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read()))
        return httpx.Response(
            200,
            json={
                "message": {
                    "thinking": "planning",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_papers",
                                "arguments": {"query": "dense retrieval"},
                            }
                        }
                    ],
                },
                "prompt_eval_count": 22,
                "eval_count": 8,
            },
        )

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            return await _adapter(http).call_tools(_tool_request())

    result = asyncio.run(exercise())
    payload = captured[0]

    assert "format" not in payload
    assert payload["tools"] == research_tool_definitions()
    assert payload["think"] is True
    assert result.calls[0]["function"]["name"] == "search_papers"
    assert result.thinking == "planning"
    assert result.prompt_tokens == 22
    assert result.output_tokens == 8
    assert result.attempts == 1


def test_missing_tool_calls_are_repaired_then_raise() -> None:
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return httpx.Response(200, json={"message": {"content": "plain text"}})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            await _adapter(http).call_tools(_tool_request(max_repair_attempts=1))

    with pytest.raises(LLMInvalidOutput) as raised:
        asyncio.run(exercise())

    assert raised.value.attempts == 2
    assert len(requests) == 2
    assert requests[1]["messages"][-2] == {
        "role": "assistant",
        "content": "plain text",
    }
    assert requests[1]["messages"][-1] == {
        "role": "user",
        "content": "Call one or more of the provided tools; reply with tool calls only.",
    }


def test_call_tools_error_mapping() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow response", request=request)

    def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="temporarily unavailable")

    def rejected(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    async def exercise(handler) -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await _adapter(http).call_tools(_tool_request())

    with pytest.raises(LLMTimeout):
        asyncio.run(exercise(timeout))
    with pytest.raises(LLMUnavailable, match="HTTP 503"):
        asyncio.run(exercise(unavailable))
    with pytest.raises(LLMRequestRejected, match="HTTP 400"):
        asyncio.run(exercise(rejected))


def test_timeout_maps_to_llm_timeout() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow response", request=request)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            await _adapter(http).generate(_call())

    with pytest.raises(LLMTimeout):
        asyncio.run(exercise())


def test_connect_error_and_5xx_map_to_unavailable() -> None:
    def connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    def server_error(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="temporarily unavailable")

    async def exercise(handler) -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await _adapter(http).generate(_call())

    with pytest.raises(LLMUnavailable, match="unavailable"):
        asyncio.run(exercise(connect_error))
    with pytest.raises(LLMUnavailable, match="HTTP 503"):
        asyncio.run(exercise(server_error))


def test_4xx_maps_to_request_rejected_with_truncated_body() -> None:
    response_body = "x" * 240

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text=response_body)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            await _adapter(http).generate(_call())

    with pytest.raises(LLMRequestRejected) as raised:
        asyncio.run(exercise())

    assert len(str(raised.value).split(": ", maxsplit=1)[1]) == 200


def test_identity_reads_version_show_and_tags_once() -> None:
    paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.17.0"})
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={"details": {"quantization_level": "Q4_K_M"}},
            )
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "other:v1", "digest": "wrong"},
                        {"name": "local-model:v1", "digest": "sha256:abc"},
                    ]
                },
            )
        raise AssertionError(f"unexpected request path: {request.url.path}")

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = _adapter(http)
            first = await client.identity()
            second = await client.identity()
            return first, second

    first, second = asyncio.run(exercise())

    assert first == second
    assert first.name == "local-model:v1"
    assert first.runtime == "ollama"
    assert first.runtime_version == "0.17.0"
    assert first.quantization == "Q4_K_M"
    assert first.digest == "sha256:abc"
    assert first.context_tokens == 8192
    assert paths == ["/api/version", "/api/show", "/api/tags"]


def test_log_event_has_no_message_content(caplog) -> None:
    private_prompt = "private prompt marker"
    private_reply = '{"answer":"private answer marker"}'
    private_thinking = "private thinking marker"

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {"content": private_reply, "thinking": private_thinking},
                "prompt_eval_count": 9,
                "eval_count": 4,
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            await _adapter(http).generate(_call(content=private_prompt))

    caplog.set_level(logging.INFO, logger="research_platform.llm")
    asyncio.run(exercise())

    records = [
        record for record in caplog.records if record.name == "research_platform.llm"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == "llm_call"
    assert record.event == "llm_call"
    assert record.kind == "plan"
    assert record.attempts == 1
    assert record.prompt_tokens == 9
    assert record.output_tokens == 4
    assert record.think is True
    assert private_prompt not in caplog.text
    assert private_reply not in caplog.text
    assert private_thinking not in caplog.text
