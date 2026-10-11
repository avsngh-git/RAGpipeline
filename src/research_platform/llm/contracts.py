"""Typed contracts for structured language model calls."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel

from research_platform.llm.types import CallKind, ModelIdentity

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ChatMessage:
    """One message in a model conversation."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class StructuredCall(Generic[T]):
    """A request for a response validated against a Pydantic model."""

    kind: CallKind
    messages: tuple[ChatMessage, ...]
    output_model: type[T]
    think: bool
    # Output cap including thinking tokens. None leaves the length to the model; the
    # call is still bounded by the client timeout and the run's wall-clock budget.
    max_output_tokens: int | None = 2048
    max_repair_attempts: int = 2
    # Added to the client's configured seed, so a retried call samples differently
    # while staying reproducible.
    seed_offset: int = 0

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("messages must contain at least one message")
        if not 0 <= self.seed_offset <= 100:
            raise ValueError("seed_offset must be between 0 and 100")
        if (
            self.max_output_tokens is not None
            and not 1 <= self.max_output_tokens <= 32768
        ):
            raise ValueError("max_output_tokens must be None or between 1 and 32768")
        if not 0 <= self.max_repair_attempts <= 5:
            raise ValueError("max_repair_attempts must be between 0 and 5")


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    """A validated response and usage details for one structured call."""

    value: T
    raw_content: str
    thinking: str | None
    prompt_tokens: int | None
    output_tokens: int | None
    duration_ms: float
    attempts: int


@dataclass(frozen=True)
class ToolCallRequest:
    """A request for one or more native model tool calls."""

    messages: tuple[ChatMessage, ...]
    tools: tuple[Mapping[str, object], ...]
    think: bool
    max_output_tokens: int = 2432
    max_repair_attempts: int = 2

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("messages must contain at least one message")
        if not self.tools:
            raise ValueError("tools must contain at least one definition")
        if not 1 <= self.max_output_tokens <= 32768:
            raise ValueError("max_output_tokens must be between 1 and 32768")
        if not 0 <= self.max_repair_attempts <= 5:
            raise ValueError("max_repair_attempts must be between 0 and 5")


@dataclass(frozen=True)
class ToolCallResult:
    """Native tool calls and usage details returned by one model request."""

    calls: tuple[Mapping[str, object], ...]
    thinking: str | None
    prompt_tokens: int | None
    output_tokens: int | None
    duration_ms: float
    attempts: int


class LLMError(Exception):
    """Base class for model adapter failures."""

    retryable: ClassVar[bool] = False


class LLMUnavailable(LLMError):
    """The model service could not serve the request."""

    retryable = True


class LLMTimeout(LLMError):
    """The model service did not respond before the configured timeout."""

    retryable = True


class LLMRequestRejected(LLMError):
    """The model service rejected the request as invalid or unsupported."""


class LLMInvalidOutput(LLMError):
    """The model exhausted its bounded attempts without valid structured output."""

    def __init__(self, message: str, *, attempts: int, content_preview: str) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.content_preview = content_preview[:200]


class LLMClient(Protocol):
    """Interface implemented by live and scripted model clients."""

    async def generate(self, call: StructuredCall[T]) -> StructuredResult[T]: ...

    async def call_tools(self, request: ToolCallRequest) -> ToolCallResult: ...

    async def identity(self) -> ModelIdentity: ...
