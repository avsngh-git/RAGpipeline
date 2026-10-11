"""OpenTelemetry tracing configuration and shared span conventions."""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypeAlias

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NoOpTracerProvider, Span, Status, StatusCode, Tracer

from research_platform.observability.content import (
    TraceContent,
    trace_content_from_env,
)
from research_platform.observability.span_export import JsonlSpanExporter

AttributeValue: TypeAlias = (
    str
    | bool
    | int
    | float
    | bytes
    | Sequence["AttributeValue"]
    | Mapping[str, "AttributeValue"]
)

TRACER_NAME: Final = "research_platform"

SPAN_RUN: Final = "research_run"
SPAN_SYNTHESIZE: Final = "synthesize"
SPAN_VERIFY: Final = "verify_citations"
SPAN_PERSIST_COMPLETE: Final = "persist.complete_run"
SPAN_PERSIST_FAIL: Final = "persist.fail_run"
SPAN_SEARCH: Final = "search"
SPAN_SEARCH_ELIGIBILITY: Final = "search.eligibility"
SPAN_SEARCH_LEXICAL: Final = "search.lexical"
SPAN_SEARCH_DENSE: Final = "search.dense"
SPAN_SEARCH_FUSION: Final = "search.fusion"
SPAN_SEARCH_RERANK: Final = "search.rerank"
SPAN_SEARCH_HYDRATE: Final = "search.hydrate"
SPAN_SEARCH_SELECT: Final = "search.select"
SPAN_CITATION_LOOKUP: Final = "citation_lookup"
SPAN_INGESTION_REQUEST: Final = "ingestion.request"
SPAN_INGESTION_PAPER: Final = "ingestion.paper"
# Dynamic names: f"node.{node_name}", f"tool.{tool_name}", f"llm.{call_kind}".

ATTR_RUN_ID: Final = "research.run_id"
ATTR_MODE: Final = "research.mode"
ATTR_STATUS: Final = "research.status"
ATTR_FAILURE_CATEGORY: Final = "research.failure_category"
ATTR_ANSWER_OUTCOME: Final = "research.answer_outcome"
ATTR_CONFIGURATION_ID: Final = "research.configuration_id"
ATTR_SNAPSHOT_ID: Final = "research.snapshot_id"
ATTR_GENERATION: Final = "research.generation"
ATTR_RETRIEVAL_PROFILE_ID: Final = "research.retrieval_profile_id"
ATTR_CODE_REVISION: Final = "research.code_revision"
ATTR_RESUME_COUNT: Final = "research.resume_count"
ATTR_REQUEST_ID: Final = "research.request_id"
ATTR_NODE: Final = "research.node"
ATTR_TOOL_NAME: Final = "research.tool.name"
ATTR_TOOL_ORDINAL: Final = "research.tool.ordinal"
ATTR_TOOL_STATUS: Final = "research.tool.status"
ATTR_TOOL_ERROR_CATEGORY: Final = "research.tool.error_category"
ATTR_TOOL_ARGUMENTS: Final = "research.tool.arguments"
ATTR_TOOL_PAPER_IDS: Final = "research.tool.paper_ids"
ATTR_TOOL_RESULT_IDS: Final = "research.tool.result_ids"
ATTR_TOOL_NEW_EVIDENCE: Final = "research.tool.new_evidence_handles"
ATTR_SEARCH_OPERATION: Final = "research.search.operation"
ATTR_SEARCH_MODE: Final = "research.search.mode"
ATTR_SEARCH_EFFECTIVE_MODE: Final = "research.search.effective_mode"
ATTR_SEARCH_ELIGIBLE: Final = "research.search.eligible_count"
ATTR_SEARCH_CANDIDATES: Final = "research.search.candidate_count"
ATTR_SEARCH_RETURNED: Final = "research.search.returned_count"
ATTR_SEARCH_FALLBACK: Final = "research.search.fallback"
ATTR_SEARCH_TOP_IDS: Final = "research.search.top_ids"
ATTR_SEARCH_TOP_SCORES: Final = "research.search.top_scores"
ATTR_SEARCH_QUERY: Final = "research.search.query"
ATTR_LLM_KIND: Final = "research.llm.kind"
ATTR_LLM_ORDINAL: Final = "research.llm.ordinal"
ATTR_LLM_ATTEMPTS: Final = "research.llm.attempts"
ATTR_LLM_THINK: Final = "research.llm.think"
ATTR_LLM_PROMPT_VERSION: Final = "research.llm.prompt_version"
ATTR_LLM_PROMPT_FINGERPRINT: Final = "research.llm.prompt_fingerprint"
ATTR_CLAIMS_DRAFTED: Final = "research.claims.drafted"
ATTR_SYNTHESIS_ATTEMPTS: Final = "research.synthesis.attempts"
ATTR_CLAIMS_KEPT: Final = "research.claims.kept"
ATTR_CLAIMS_REJECTED: Final = "research.claims.rejected"
ATTR_CLAIMS_UNSUPPORTED: Final = "research.claims.unsupported"
ATTR_CLAIMS_VERDICTS: Final = "research.claims.verdicts"
ATTR_INGESTION_REQUEST_ID: Final = "research.ingestion.request_id"
ATTR_INGESTION_PAPER_ID: Final = "research.ingestion.paper_id"
ATTR_INGESTION_PAPER_COUNT: Final = "research.ingestion.paper_count"
ATTR_INGESTION_STATUS: Final = "research.ingestion.status"
ATTR_INGESTION_REASON: Final = "research.ingestion.reason"
ATTR_INGESTION_WAITED_SECONDS: Final = "research.ingestion.waited_seconds"

LF_OBSERVATION_TYPE: Final = "langfuse.observation.type"
LF_INPUT: Final = "langfuse.observation.input"
LF_OUTPUT: Final = "langfuse.observation.output"
LF_LEVEL: Final = "langfuse.observation.level"
LF_TRACE_NAME: Final = "langfuse.trace.name"
LF_SESSION_ID: Final = "langfuse.session.id"
GEN_AI_REQUEST_MODEL: Final = "gen_ai.request.model"
GEN_AI_INPUT_TOKENS: Final = "gen_ai.usage.input_tokens"
GEN_AI_OUTPUT_TOKENS: Final = "gen_ai.usage.output_tokens"


@dataclass(frozen=True)
class TracingSettings:
    """Where spans go and how much content they may hold."""

    enabled: bool
    content: TraceContent
    jsonl_dir: Path | None
    otlp_endpoint: str | None
    otlp_headers: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_env(
        cls, environment: str, environ: Mapping[str, str] | None = None
    ) -> TracingSettings:
        """Build tracing settings from the process environment."""
        source = os.environ if environ is None else environ
        enabled_value = source.get("RESEARCH_PLATFORM_TRACING")
        if enabled_value is None:
            enabled = environment != "test"
        elif enabled_value == "on":
            enabled = True
        elif enabled_value == "off":
            enabled = False
        else:
            raise ValueError("RESEARCH_PLATFORM_TRACING must be on or off")

        trace_dir = source.get("RESEARCH_PLATFORM_TRACE_DIR")
        if trace_dir is not None:
            jsonl_dir = Path(trace_dir) if trace_dir else None
        elif environment == "development":
            jsonl_dir = Path("local-reference/traces")
        else:
            jsonl_dir = None

        endpoint = source.get("RESEARCH_PLATFORM_OTLP_ENDPOINT") or None
        public_key = source.get("LANGFUSE_PUBLIC_KEY", "")
        secret_key = source.get("LANGFUSE_SECRET_KEY", "")
        headers: tuple[tuple[str, str], ...] = ()
        if public_key and secret_key:
            credentials = base64.b64encode(
                f"{public_key}:{secret_key}".encode()
            ).decode()
            headers = (
                ("Authorization", f"Basic {credentials}"),
                ("x-langfuse-ingestion-version", "4"),
            )

        return cls(
            enabled=enabled,
            content=trace_content_from_env(environment, source),
            jsonl_dir=jsonl_dir,
            otlp_endpoint=endpoint,
            otlp_headers=headers,
        )


_provider: TracerProvider | None = None
_content: TraceContent = TraceContent.IDS


def configure_tracing(settings: TracingSettings, *, service_name: str) -> None:
    """Install this process's tracer provider; replaces any earlier one."""
    global _provider, _content

    shutdown_tracing()
    _content = settings.content
    if not settings.enabled:
        _provider = None
        return

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if settings.jsonl_dir is not None:
        settings.jsonl_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        provider.add_span_processor(
            BatchSpanProcessor(
                JsonlSpanExporter(settings.jsonl_dir / f"{service_name}.jsonl")
            )
        )
    if settings.otlp_endpoint is not None:
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=settings.otlp_endpoint,
                    headers=dict(settings.otlp_headers),
                )
            )
        )
    _provider = provider


def shutdown_tracing() -> None:
    """Flush and shut down the provider, if any."""
    global _provider

    provider = _provider
    _provider = None
    if provider is not None:
        provider.shutdown()


# An exception's message can hold prompt, model output or passage text (for example a
# pydantic error's input_value), so spans record only its type unless content is FULL.
ATTR_ERROR_TYPE: Final = "error.type"
ATTR_ERROR_MESSAGE: Final = "research.error.message"


class PrivateTracer:
    """A tracer whose spans store exception text only at content FULL.

    OpenTelemetry's defaults (``record_exception`` and ``set_status_on_exception``)
    store the exception message and stack trace as a span event and status
    description at every content level. These spans instead set an ERROR status with
    no description and ``error.type``, plus the message at FULL. A caller that passes
    ``set_status_on_exception`` handles errors itself and is left alone.
    """

    def __init__(self, inner: Tracer) -> None:
        self._inner = inner

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        *,
        record_exception: bool = False,
        set_status_on_exception: bool | None = None,
        **kwargs: Any,
    ) -> Iterator[Span]:
        mark_errors = set_status_on_exception is None
        with self._inner.start_as_current_span(
            name,
            record_exception=record_exception,
            set_status_on_exception=bool(set_status_on_exception),
            **kwargs,
        ) as span:
            try:
                yield span
            except BaseException as error:
                if mark_errors and not isinstance(error, GeneratorExit):
                    mark_span_error(span, error)
                raise


def mark_span_error(span: Span, error: BaseException) -> None:
    """Set ERROR status and the error type; the message only at content FULL."""
    span.set_status(Status(StatusCode.ERROR))
    span.set_attribute(ATTR_ERROR_TYPE, type(error).__qualname__)
    if _content is TraceContent.FULL:
        span.set_attribute(ATTR_ERROR_MESSAGE, str(error)[:100_000])


def get_tracer() -> PrivateTracer:
    """The tracer to use at call time; a no-op tracer when tracing is off."""
    return PrivateTracer((_provider or NoOpTracerProvider()).get_tracer(TRACER_NAME))


def trace_content() -> TraceContent:
    """The content level spans may hold."""
    return _content


def set_id_attribute(span: Span, key: str, value: AttributeValue | None) -> None:
    """Set an identifier or score unless content is NONE or the value is None."""
    if _content is not TraceContent.NONE and value is not None:
        span.set_attribute(key, value)


def set_text_attribute(span: Span, key: str, value: str | None) -> None:
    """Set text only at content FULL; truncate to 100,000 characters."""
    if _content is TraceContent.FULL and value is not None:
        span.set_attribute(key, value[:100_000])


@contextmanager
def capture_spans(
    content: TraceContent = TraceContent.IDS,
) -> Iterator[InMemorySpanExporter]:
    """Route spans to memory for a test, restoring the previous state afterwards."""
    global _provider, _content

    previous_provider = _provider
    previous_content = _content
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    _provider = provider
    _content = content
    try:
        yield exporter
    finally:
        provider.shutdown()
        _provider = previous_provider
        _content = previous_content
