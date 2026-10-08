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


class DecodingSettings(BaseModel):
    """Model options the live adapter sends with every call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int = Field(ge=0)
    context_tokens: int = Field(ge=512)
    timeout_seconds: float = Field(gt=0)
    temperature: float | None = None
    top_k: int | None = Field(None, ge=1)
    top_p: float | None = Field(None, gt=0, le=1)
    presence_penalty: float | None = None

    def sampling_options(self) -> dict[str, float | int]:
        """The sampling options to send, leaving out any not set."""
        values = {
            "temperature": self.temperature,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "presence_penalty": self.presence_penalty,
        }
        return {name: value for name, value in values.items() if value is not None}


class ModelIdentity(BaseModel):
    """Identifies the model and runtime used for a call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    runtime: str
    runtime_version: str | None = None
    digest: str | None = None
    quantization: str | None = None
    context_tokens: int = Field(ge=512)
