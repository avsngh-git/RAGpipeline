"""Deterministic model client for offline workflows and tests."""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

from research_platform.llm.contracts import (
    LLMError,
    LLMInvalidOutput,
    StructuredCall,
    StructuredResult,
    ToolCallRequest,
    ToolCallResult,
)
from research_platform.llm.types import CallKind, ModelIdentity

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ScriptedReply:
    """One expected model reply or typed failure."""

    kind: CallKind
    content: str | None = None
    tool_calls: tuple[Mapping[str, object], ...] | None = None
    error: LLMError | None = None

    def __post_init__(self) -> None:
        present = sum(
            value is not None for value in (self.content, self.tool_calls, self.error)
        )
        if present != 1:
            raise ValueError("exactly one of content, tool_calls or error is required")


class ScriptedLLM:
    """Consume predefined replies while recording every model call."""

    def __init__(
        self,
        replies: Sequence[ScriptedReply],
        *,
        identity: ModelIdentity | None = None,
    ) -> None:
        self._replies = deque(replies)
        self._identity = identity or ModelIdentity(
            name="scripted",
            runtime="scripted",
            context_tokens=16384,
        )
        self.calls: list[StructuredCall[Any]] = []
        self.tool_requests: list[ToolCallRequest] = []

    @property
    def remaining(self) -> int:
        """Return the number of replies not yet consumed."""

        return len(self._replies)

    async def generate(self, call: StructuredCall[T]) -> StructuredResult[T]:
        """Return the next matching reply, validated against the requested model."""

        self.calls.append(call)
        if not self._replies:
            raise AssertionError(
                f"script exhausted; expected {call.kind.value}, actual <none>"
            )

        reply = self._replies.popleft()
        if reply.kind != call.kind:
            raise AssertionError(
                f"script kind mismatch; expected {call.kind.value}, "
                f"actual {reply.kind.value}"
            )
        if reply.error is not None:
            raise reply.error

        content = reply.content
        assert content is not None
        try:
            value = call.output_model.model_validate_json(content)
        except ValidationError as exc:
            raise LLMInvalidOutput(
                str(exc).splitlines()[0][:300],
                attempts=1,
                content_preview=content,
            ) from exc

        return StructuredResult(
            value=value,
            raw_content=content,
            thinking=None,
            prompt_tokens=None,
            output_tokens=None,
            duration_ms=0.0,
            attempts=1,
        )

    async def call_tools(self, request: ToolCallRequest) -> ToolCallResult:
        """Return the next scripted native tool-call reply."""
        self.tool_requests.append(request)
        if not self._replies:
            raise AssertionError("script exhausted; expected plan, actual <none>")

        reply = self._replies.popleft()
        if reply.kind is not CallKind.PLAN:
            raise AssertionError(
                f"script kind mismatch; expected plan, actual {reply.kind.value}"
            )
        if reply.error is not None:
            raise reply.error
        if reply.tool_calls is None:
            raise AssertionError("script reply did not contain tool_calls")

        return ToolCallResult(
            calls=reply.tool_calls,
            thinking=None,
            prompt_tokens=None,
            output_tokens=None,
            duration_ms=0.0,
            attempts=1,
        )

    async def identity(self) -> ModelIdentity:
        """Return the configured scripted model identity."""

        return self._identity
