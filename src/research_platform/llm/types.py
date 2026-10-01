"""Shared language model identity and call types."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CallKind(StrEnum):
    """Kinds of model calls made during a research run."""

    PLAN = "plan"
    EVALUATE = "evaluate"
    SYNTHESIZE = "synthesize"
    JUDGE = "judge"
    PROBE = "probe"


class ModelIdentity(BaseModel):
    """Identifies the model and runtime used for a call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    runtime: str
    runtime_version: str | None = None
    digest: str | None = None
    quantization: str | None = None
    context_tokens: int = Field(ge=512)
