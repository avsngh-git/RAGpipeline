"""Ollama adapter for schema-constrained chat completions."""

from __future__ import annotations

import logging
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from research_platform.config import Settings
from research_platform.llm.contracts import (
    LLMInvalidOutput,
    LLMRequestRejected,
    LLMTimeout,
    LLMUnavailable,
    StructuredCall,
    StructuredResult,
    ToolCallRequest,
    ToolCallResult,
)
from research_platform.llm.types import ModelIdentity

logger = logging.getLogger("research_platform.llm")
T = TypeVar("T", bound=BaseModel)


class OllamaClient:
    """Call Ollama's chat API and validate each response against its schema."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        base_url: str,
        model: str,
        context_tokens: int,
        timeout_seconds: float,
        seed: int,
    ) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._context_tokens = context_tokens
        self._timeout_seconds = timeout_seconds
        self._seed = seed
        self._identity: ModelIdentity | None = None

    @classmethod
    def from_settings(cls, http: httpx.AsyncClient, settings: Settings) -> OllamaClient:
        """Build an adapter from validated application settings."""

        return cls(
            http,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            context_tokens=settings.llm_context_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
            seed=settings.llm_seed,
        )

    async def generate(self, call: StructuredCall[T]) -> StructuredResult[T]:
        """Generate and validate a response, repairing schema errors within the call budget."""

        started_at = time.perf_counter()
        attempts = 0
        prompt_tokens: int | None = None
        output_tokens: int | None = None
        messages = [
            {"role": message.role, "content": message.content}
            for message in call.messages
        ]

        try:
            while True:
                attempts += 1
                payload = await self._request_json(
                    "POST",
                    "/api/chat",
                    body={
                        "model": self._model,
                        "messages": messages,
                        "stream": False,
                        "format": call.output_model.model_json_schema(),
                        "think": call.think,
                        "options": {
                            "num_ctx": self._context_tokens,
                            "num_predict": (
                                -1
                                if call.max_output_tokens is None
                                else call.max_output_tokens
                            ),
                            "seed": self._seed,
                        },
                    },
                )

                message = payload.get("message")
                raw_content_value = (
                    message.get("content") if isinstance(message, dict) else None
                )
                raw_content = (
                    raw_content_value
                    if isinstance(raw_content_value, str)
                    else str(raw_content_value or "")
                )
                thinking_value = (
                    message.get("thinking") if isinstance(message, dict) else None
                )
                thinking = thinking_value if isinstance(thinking_value, str) else None
                prompt_tokens = self._accumulate_count(
                    prompt_tokens, payload.get("prompt_eval_count")
                )
                output_tokens = self._accumulate_count(
                    output_tokens, payload.get("eval_count")
                )

                try:
                    if not isinstance(raw_content_value, str):
                        raise ValueError("Ollama reply did not include message.content")
                    value = call.output_model.model_validate_json(raw_content)
                except (ValidationError, ValueError) as exc:
                    if attempts > call.max_repair_attempts:
                        raise LLMInvalidOutput(
                            str(exc).splitlines()[0][:300],
                            attempts=attempts,
                            content_preview=raw_content,
                        ) from exc

                    validation_message = str(exc).splitlines()[0][:300]
                    messages.extend(
                        [
                            {"role": "assistant", "content": raw_content},
                            {
                                "role": "user",
                                "content": (
                                    "Your previous reply did not match the required JSON "
                                    f"schema: {validation_message}. Reply again with only "
                                    "JSON that matches the schema."
                                ),
                            },
                        ]
                    )
                    continue

                return StructuredResult(
                    value=value,
                    raw_content=raw_content,
                    thinking=thinking,
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    duration_ms=(time.perf_counter() - started_at) * 1000,
                    attempts=attempts,
                )
        finally:
            logger.info(
                "llm_call",
                extra={
                    "event": "llm_call",
                    "kind": call.kind.value,
                    "attempts": attempts,
                    "duration_ms": (time.perf_counter() - started_at) * 1000,
                    "prompt_tokens": prompt_tokens,
                    "output_tokens": output_tokens,
                    "think": call.think,
                },
            )

    async def call_tools(self, request: ToolCallRequest) -> ToolCallResult:
        """Request native tool calls and repair replies that omit all calls."""
        started_at = time.perf_counter()
        attempts = 0
        prompt_tokens: int | None = None
        output_tokens: int | None = None
        messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
        ]

        try:
            while True:
                attempts += 1
                payload = await self._request_json(
                    "POST",
                    "/api/chat",
                    body={
                        "model": self._model,
                        "messages": messages,
                        "stream": False,
                        "think": request.think,
                        "tools": [dict(tool) for tool in request.tools],
                        "options": {
                            "num_ctx": self._context_tokens,
                            "num_predict": request.max_output_tokens,
                            "seed": self._seed,
                        },
                    },
                )
                message_value = payload.get("message")
                message = message_value if isinstance(message_value, dict) else {}
                calls_value = message.get("tool_calls")
                prompt_tokens = self._accumulate_count(
                    prompt_tokens, payload.get("prompt_eval_count")
                )
                output_tokens = self._accumulate_count(
                    output_tokens, payload.get("eval_count")
                )

                if isinstance(calls_value, list) and calls_value:
                    calls = tuple(
                        dict(call) for call in calls_value if isinstance(call, dict)
                    )
                    if len(calls) == len(calls_value):
                        thinking_value = message.get("thinking")
                        return ToolCallResult(
                            calls=calls,
                            thinking=(
                                thinking_value
                                if isinstance(thinking_value, str)
                                else None
                            ),
                            prompt_tokens=prompt_tokens,
                            output_tokens=output_tokens,
                            duration_ms=(time.perf_counter() - started_at) * 1000,
                            attempts=attempts,
                        )

                content_value = message.get("content")
                content = content_value if isinstance(content_value, str) else ""
                if attempts > request.max_repair_attempts:
                    raise LLMInvalidOutput(
                        "Ollama reply did not contain tool_calls",
                        attempts=attempts,
                        content_preview=content,
                    )
                assistant_message: dict[str, Any] = {
                    "role": "assistant",
                    "content": content,
                }
                thinking_value = message.get("thinking")
                if isinstance(thinking_value, str):
                    assistant_message["thinking"] = thinking_value
                messages.extend(
                    [
                        assistant_message,
                        {
                            "role": "user",
                            "content": (
                                "Call one or more of the provided tools; reply with "
                                "tool calls only."
                            ),
                        },
                    ]
                )
        finally:
            logger.info(
                "llm_call",
                extra={
                    "event": "llm_call",
                    "kind": "plan",
                    "format": "tools",
                    "attempts": attempts,
                    "duration_ms": (time.perf_counter() - started_at) * 1000,
                    "prompt_tokens": prompt_tokens,
                    "output_tokens": output_tokens,
                    "think": request.think,
                },
            )

    async def identity(self) -> ModelIdentity:
        """Read and cache the runtime and model identity reported by Ollama."""

        if self._identity is not None:
            return self._identity

        version = await self._request_json("GET", "/api/version")
        details = await self._request_json(
            "POST", "/api/show", body={"model": self._model}
        )
        tags = await self._request_json("GET", "/api/tags")

        version_value = version.get("version")
        runtime_version = version_value if isinstance(version_value, str) else None
        details_value = details.get("details")
        quantization_value = (
            details_value.get("quantization_level")
            if isinstance(details_value, dict)
            else None
        )
        models_value = tags.get("models")
        digest: str | None = None
        if isinstance(models_value, list):
            wanted_names = {self._model}
            if ":" not in self._model:
                wanted_names.add(f"{self._model}:latest")
            for model in models_value:
                if not isinstance(model, dict):
                    continue
                if wanted_names.intersection({model.get("name"), model.get("model")}):
                    digest_value = model.get("digest")
                    digest = digest_value if isinstance(digest_value, str) else None
                    break

        self._identity = ModelIdentity(
            name=self._model,
            runtime="ollama",
            runtime_version=runtime_version,
            digest=digest,
            quantization=(
                quantization_value if isinstance(quantization_value, str) else None
            ),
            context_tokens=self._context_tokens,
        )
        return self._identity

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            if body is None:
                response = await self._http.request(
                    method, url, timeout=self._timeout_seconds
                )
            else:
                response = await self._http.request(
                    method,
                    url,
                    json=body,
                    timeout=self._timeout_seconds,
                )
        except httpx.TimeoutException as exc:
            raise LLMTimeout("Ollama request timed out") from exc
        except httpx.TransportError as exc:
            raise LLMUnavailable("Ollama is unavailable") from exc

        if response.status_code >= 500:
            raise LLMUnavailable(f"Ollama returned HTTP {response.status_code}")
        if response.status_code >= 400:
            body_preview = response.text[:200]
            raise LLMRequestRejected(
                f"Ollama returned HTTP {response.status_code}: {body_preview}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMUnavailable("Ollama returned an invalid JSON response") from exc
        if not isinstance(payload, dict):
            raise LLMUnavailable("Ollama returned an invalid JSON response")
        return payload

    @staticmethod
    def _accumulate_count(current: int | None, value: object) -> int | None:
        if not isinstance(value, int) or isinstance(value, bool):
            return current
        return (current or 0) + value
