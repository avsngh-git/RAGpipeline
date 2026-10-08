"""Persist one record per model call made during a research run (ADR-0026)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from typing import Protocol, TypeVar
from uuid import UUID

from opentelemetry.trace import Span, Status, StatusCode
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
from research_platform.observability.metrics import LLM_CALLS, LLM_LATENCY, LLM_TOKENS
from research_platform.observability.tracing import (
    ATTR_LLM_ATTEMPTS,
    ATTR_LLM_KIND,
    ATTR_LLM_ORDINAL,
    ATTR_LLM_PROMPT_FINGERPRINT,
    ATTR_LLM_PROMPT_VERSION,
    ATTR_LLM_THINK,
    GEN_AI_INPUT_TOKENS,
    GEN_AI_OUTPUT_TOKENS,
    GEN_AI_REQUEST_MODEL,
    LF_INPUT,
    LF_LEVEL,
    LF_OBSERVATION_TYPE,
    LF_OUTPUT,
    get_tracer,
    set_text_attribute,
)
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
            "seed_offset": call.seed_offset,
        }
        started = time.perf_counter()
        with get_tracer().start_as_current_span(
            f"llm.{call.kind.value}",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            self._set_generation_attributes(span, call.kind, call.think)
            set_text_attribute(span, LF_INPUT, _messages_json(call.messages))
            try:
                result = await self._inner.generate(call)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self._record_failure(
                    call.kind,
                    call.think,
                    options,
                    started,
                    error,
                    call.messages,
                    span,
                )
                raise
            span.set_attribute(ATTR_LLM_ATTEMPTS, result.attempts)
            if isinstance(result.prompt_tokens, int):
                span.set_attribute(GEN_AI_INPUT_TOKENS, result.prompt_tokens)
            if isinstance(result.output_tokens, int):
                span.set_attribute(GEN_AI_OUTPUT_TOKENS, result.output_tokens)
            set_text_attribute(
                span,
                LF_OUTPUT,
                json.dumps(
                    {"content": result.raw_content, "thinking": result.thinking}
                ),
            )
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
                span=span,
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
        kind = CallKind.PLAN
        with get_tracer().start_as_current_span(
            f"llm.{kind.value}",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            self._set_generation_attributes(span, kind, request.think)
            set_text_attribute(span, LF_INPUT, _messages_json(request.messages))
            try:
                result = await self._inner.call_tools(request)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self._record_failure(
                    kind,
                    request.think,
                    options,
                    started,
                    error,
                    request.messages,
                    span,
                )
                raise
            raw = json.dumps(
                [dict(call) for call in result.calls], sort_keys=True, default=str
            )
            span.set_attribute(ATTR_LLM_ATTEMPTS, result.attempts)
            if isinstance(result.prompt_tokens, int):
                span.set_attribute(GEN_AI_INPUT_TOKENS, result.prompt_tokens)
            if isinstance(result.output_tokens, int):
                span.set_attribute(GEN_AI_OUTPUT_TOKENS, result.output_tokens)
            set_text_attribute(
                span,
                LF_OUTPUT,
                json.dumps({"content": raw, "thinking": result.thinking}),
            )
            await self._record(
                kind=kind,
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
                    output=raw,
                    thinking=result.thinking,
                ),
                span=span,
            )
        return result

    def _set_generation_attributes(
        self, span: Span, kind: CallKind, think: bool
    ) -> None:
        span.set_attribute(LF_OBSERVATION_TYPE, "generation")
        span.set_attribute(GEN_AI_REQUEST_MODEL, self._model_name)
        span.set_attribute(ATTR_LLM_KIND, kind.value)
        span.set_attribute(ATTR_LLM_THINK, think)
        prompt_version = self._prompt_versions.get(kind.value)
        if prompt_version is not None:
            span.set_attribute(ATTR_LLM_PROMPT_VERSION, prompt_version)
        prompt_fingerprint = self._prompt_fingerprints.get(kind.value)
        if prompt_fingerprint is not None:
            span.set_attribute(ATTR_LLM_PROMPT_FINGERPRINT, prompt_fingerprint)

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
        span: Span,
    ) -> None:
        attempts = getattr(error, "attempts", 1)
        preview = getattr(error, "content_preview", None)
        span.set_attribute(LF_LEVEL, "ERROR")
        span.set_status(Status(StatusCode.ERROR, type(error).__name__))
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
            span=span,
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
        span: Span,
    ) -> int:
        if self._decoding is not None:
            options = options | {
                "num_ctx": self._decoding.context_tokens,
                "seed": self._decoding.seed + _seed_offset(options),
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
            trace_id=_span_id(span, "trace_id", 32),
            span_id=_span_id(span, "span_id", 16),
        )
        record_id = await self._sink.append_llm_call(
            self._run_id, record, payload if self._store_payloads else None
        )
        span.set_attribute(ATTR_LLM_ORDINAL, record_id)
        LLM_CALLS.labels(kind.value, status).inc()
        LLM_LATENCY.labels(kind.value).observe(record.duration_ms / 1000)
        if isinstance(prompt_tokens, int):
            LLM_TOKENS.labels(kind.value, "input").inc(prompt_tokens)
        if isinstance(output_tokens, int):
            LLM_TOKENS.labels(kind.value, "output").inc(output_tokens)
        return record_id


def _messages_json(messages: tuple[ChatMessage, ...]) -> str:
    return json.dumps(
        [{"role": message.role, "content": message.content} for message in messages]
    )


def _span_id(span: Span, field: str, width: int) -> str | None:
    context = span.get_span_context()
    if not context.is_valid:
        return None
    return format(getattr(context, field), f"0{width}x")


def _tool_names(tools: tuple[Mapping[str, object], ...]) -> list[str]:
    names: list[str] = []
    for tool in tools:
        function = tool.get("function")
        if isinstance(function, Mapping):
            name = function.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def _seed_offset(options: dict[str, object]) -> int:
    offset = options.get("seed_offset", 0)
    return offset if isinstance(offset, int) else 0
