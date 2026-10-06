"""Persist one record per model call made during a research run (ADR-0026)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from typing import Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel

from research_platform.llm.contracts import (
    ChatMessage,
    LLMClient,
    StructuredCall,
    StructuredResult,
    ToolCallRequest,
    ToolCallResult,
)
from research_platform.llm.types import CallKind, DecodingSettings, ModelIdentity
from research_platform.runs.llm_records import (
    LLMCallPayload,
    LLMCallRecord,
    LLMCallStatus,
)

T = TypeVar("T", bound=BaseModel)


class LLMCallSink(Protocol):
    """Persists model call records for one run."""

    async def append_llm_call(
        self,
        run_id: UUID,
        record: LLMCallRecord,
        payload: LLMCallPayload | None = None,
    ) -> int: ...


class RecordingLLMClient:
    """An LLMClient that persists one record per call made through it."""

    def __init__(
        self,
        inner: LLMClient,
        *,
        sink: LLMCallSink,
        run_id: UUID,
        model_name: str,
        store_payloads: bool,
        prompt_versions: Mapping[str, str],
        prompt_fingerprints: Mapping[str, str],
        decoding: DecodingSettings | None,
    ) -> None:
        self._inner = inner
        self._sink = sink
        self._run_id = run_id
        self._model_name = model_name
        self._store_payloads = store_payloads
        self._prompt_versions = dict(prompt_versions)
        self._prompt_fingerprints = dict(prompt_fingerprints)
        self._decoding = decoding

    async def generate(self, call: StructuredCall[T]) -> StructuredResult[T]:
        """Run a structured call and record its outcome."""
        options: dict[str, object] = {
            "think": call.think,
            "num_predict": (
                -1 if call.max_output_tokens is None else call.max_output_tokens
            ),
            "max_repair_attempts": call.max_repair_attempts,
        }
        started = time.perf_counter()
        try:
            result = await self._inner.generate(call)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._record_failure(
                call.kind, call.think, options, started, error, call.messages
            )
            raise
        await self._record(
            kind=call.kind,
            think=call.think,
            options=options,
            started=started,
            status="succeeded",
            attempts=result.attempts,
            prompt_tokens=result.prompt_tokens,
            output_tokens=result.output_tokens,
            thinking=result.thinking,
            payload=LLMCallPayload(
                messages=call.messages,
                output=result.raw_content,
                thinking=result.thinking,
            ),
        )
        return result

    async def call_tools(self, request: ToolCallRequest) -> ToolCallResult:
        """Run a native tool-call request and record it as a plan call."""
        options: dict[str, object] = {
            "think": request.think,
            "num_predict": request.max_output_tokens,
            "max_repair_attempts": request.max_repair_attempts,
            "tools": _tool_names(request.tools),
        }
        started = time.perf_counter()
        try:
            result = await self._inner.call_tools(request)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._record_failure(
                CallKind.PLAN, request.think, options, started, error, request.messages
            )
            raise
        await self._record(
            kind=CallKind.PLAN,
            think=request.think,
            options=options,
            started=started,
            status="succeeded",
            attempts=result.attempts,
            prompt_tokens=result.prompt_tokens,
            output_tokens=result.output_tokens,
            thinking=result.thinking,
            payload=LLMCallPayload(
                messages=request.messages,
                output=json.dumps(
                    [dict(call) for call in result.calls], sort_keys=True, default=str
                ),
                thinking=result.thinking,
            ),
        )
        return result

    async def identity(self) -> ModelIdentity:
        """Return the wrapped client's model identity."""
        return await self._inner.identity()

    async def _record_failure(
        self,
        kind: CallKind,
        think: bool,
        options: dict[str, object],
        started: float,
        error: Exception,
        messages: tuple[ChatMessage, ...],
    ) -> None:
        attempts = getattr(error, "attempts", 1)
        preview = getattr(error, "content_preview", None)
        await self._record(
            kind=kind,
            think=think,
            options=options,
            started=started,
            status="failed",
            attempts=attempts if isinstance(attempts, int) else 1,
            error_type=type(error).__name__,
            payload=LLMCallPayload(
                messages=messages,
                error_preview=preview if isinstance(preview, str) else None,
            ),
        )

    async def _record(
        self,
        *,
        kind: CallKind,
        think: bool,
        options: dict[str, object],
        started: float,
        status: LLMCallStatus,
        attempts: int,
        payload: LLMCallPayload,
        prompt_tokens: int | None = None,
        output_tokens: int | None = None,
        thinking: str | None = None,
        error_type: str | None = None,
    ) -> int:
        if self._decoding is not None:
            options = options | {
                "num_ctx": self._decoding.context_tokens,
                "seed": self._decoding.seed,
                "temperature": self._decoding.temperature,
            }
        record = LLMCallRecord(
            kind=kind,
            status=status,
            model_name=self._model_name,
            think=think,
            attempts=attempts,
            duration_ms=(time.perf_counter() - started) * 1000,
            options=options,
            prompt_version=self._prompt_versions.get(kind.value),
            prompt_fingerprint=self._prompt_fingerprints.get(kind.value),
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            thinking_chars=len(thinking) if thinking else None,
            error_type=error_type,
        )
        return await self._sink.append_llm_call(
            self._run_id, record, payload if self._store_payloads else None
        )


def _tool_names(tools: tuple[Mapping[str, object], ...]) -> list[str]:
    names: list[str] = []
    for tool in tools:
        function = tool.get("function")
        if isinstance(function, Mapping):
            name = function.get("name")
            if isinstance(name, str):
                names.append(name)
    return names
