"""Model generation and answer-verification spans follow the trace contract."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

import pytest
from opentelemetry.trace import StatusCode
from pydantic import BaseModel

from research_platform.agents.answering import VerifiedAnswer, answer_question
from research_platform.agents.evidence import EvidenceRegistry
from research_platform.llm.contracts import (
    ChatMessage,
    LLMUnavailable,
    StructuredCall,
)
from research_platform.llm.recording import RecordingLLMClient
from research_platform.llm.scripted import ScriptedLLM, ScriptedReply
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.observability.content import TraceContent
from research_platform.observability.tracing import (
    ATTR_CLAIMS_DRAFTED,
    ATTR_CLAIMS_KEPT,
    ATTR_CLAIMS_REJECTED,
    ATTR_CLAIMS_UNSUPPORTED,
    ATTR_LLM_KIND,
    ATTR_LLM_PROMPT_VERSION,
    GEN_AI_REQUEST_MODEL,
    LF_INPUT,
    LF_LEVEL,
    LF_OBSERVATION_TYPE,
    LF_OUTPUT,
    SPAN_SYNTHESIZE,
    SPAN_VERIFY,
    capture_spans,
    get_tracer,
)
from research_platform.runs.contracts import ResearchMode, ResearchRequest, RunBudgets
from research_platform.runs.memory import InMemoryRunStore
from research_platform.tools.research_tools import CollectedEvidence

_IDENTITY = ModelIdentity(name="scripted", runtime="scripted", context_tokens=8192)
_MESSAGES = (ChatMessage("system", "zq7731"), ChatMessage("user", "zq7731"))


class _Answer(BaseModel):
    value: str


async def _client(
    reply: ScriptedReply,
) -> tuple[InMemoryRunStore, UUID, RecordingLLMClient]:
    store = InMemoryRunStore()
    run_id = await store.create_run(
        ResearchRequest(question="zq7731", mode=ResearchMode.QUICK)
    )
    client = RecordingLLMClient(
        ScriptedLLM((reply,), identity=_IDENTITY),
        sink=store,
        run_id=run_id,
        model_name="scripted-model",
        store_payloads=False,
        prompt_versions={"synthesize": "prompt-v1"},
        prompt_fingerprints={},
        decoding=None,
    )
    return store, run_id, client


def _call() -> StructuredCall[_Answer]:
    return StructuredCall(
        kind=CallKind.SYNTHESIZE,
        messages=_MESSAGES,
        output_model=_Answer,
        think=False,
    )


async def _verified_answer() -> tuple[InMemoryRunStore, UUID, VerifiedAnswer]:
    passage = "zq7731 reports a synthetic retrieval gain of 4.5 points."
    evidence = CollectedEvidence(
        chunk_id="chunk-zq7731",
        paper_id="paper-zq7731",
        text=passage,
        title="Synthetic paper",
        publication_year=2025,
        kind="prose",
        source_location={},
        reranker_score=None,
    )
    registry, _ = EvidenceRegistry().register((evidence,), max_passages=1)
    reply = ScriptedReply(
        kind=CallKind.SYNTHESIZE,
        content=json.dumps(
            {
                "relevant_handles": ["E1"],
                "insufficient_evidence": False,
                "claims": [
                    {
                        "handle": "E1",
                        "quote": passage,
                        "text": "The synthetic retrieval gain was 4.5 points.",
                    }
                ],
                "answer": "Synthetic answer.",
            }
        ),
    )
    store, run_id, client = await _client(reply)
    with get_tracer().start_as_current_span("node.answer"):
        result = await answer_question(
            client,
            question="zq7731",
            registry=registry,
            texts={evidence.chunk_id: passage},
            budgets=RunBudgets(),
            thinking=frozenset(),
        )
    return store, run_id, result


def test_generation_span_attributes() -> None:
    async def exercise() -> None:
        store, run_id, client = await _client(
            ScriptedReply(kind=CallKind.SYNTHESIZE, content='{"value":"zq7731"}')
        )
        with capture_spans() as exporter:
            await client.generate(_call())
        span = next(
            s for s in exporter.get_finished_spans() if s.name == "llm.synthesize"
        )
        attributes = span.attributes or {}

        assert attributes[LF_OBSERVATION_TYPE] == "generation"
        assert attributes[GEN_AI_REQUEST_MODEL] == "scripted-model"
        assert attributes[ATTR_LLM_KIND] == "synthesize"
        assert attributes[ATTR_LLM_PROMPT_VERSION] == "prompt-v1"
        assert (await store.list_llm_calls(run_id))[0].ordinal == attributes[
            "research.llm.ordinal"
        ]

    asyncio.run(exercise())


def test_input_output_absent_at_ids() -> None:
    async def exercise() -> None:
        _store, _run_id, client = await _client(
            ScriptedReply(kind=CallKind.SYNTHESIZE, content='{"value":"zq7731"}')
        )
        with capture_spans(TraceContent.IDS) as exporter:
            await client.generate(_call())
        attributes = next(
            s.attributes or {}
            for s in exporter.get_finished_spans()
            if s.name == "llm.synthesize"
        )

        assert LF_INPUT not in attributes
        assert LF_OUTPUT not in attributes

    asyncio.run(exercise())


def test_input_output_present_at_full() -> None:
    async def exercise() -> None:
        _store, _run_id, client = await _client(
            ScriptedReply(kind=CallKind.SYNTHESIZE, content='{"value":"zq7731"}')
        )
        with capture_spans(TraceContent.FULL) as exporter:
            await client.generate(_call())
        attributes = next(
            s.attributes or {}
            for s in exporter.get_finished_spans()
            if s.name == "llm.synthesize"
        )

        input_value = json.loads(attributes[LF_INPUT])
        output_value = json.loads(attributes[LF_OUTPUT])
        assert isinstance(input_value, list)
        assert output_value["content"] == '{"value":"zq7731"}'

    asyncio.run(exercise())


def test_failed_call_span_is_error() -> None:
    async def exercise() -> None:
        store, run_id, client = await _client(
            ScriptedReply(kind=CallKind.SYNTHESIZE, error=LLMUnavailable("zq7731"))
        )
        with capture_spans() as exporter:
            with pytest.raises(LLMUnavailable):
                await client.generate(_call())
        span = next(
            s for s in exporter.get_finished_spans() if s.name == "llm.synthesize"
        )

        assert span.status.status_code is StatusCode.ERROR
        assert span.status.description == "LLMUnavailable"
        assert (span.attributes or {})[LF_LEVEL] == "ERROR"
        assert (await store.list_llm_calls(run_id))[0].record.status == "failed"

    asyncio.run(exercise())


def test_record_carries_span_ids() -> None:
    async def exercise() -> None:
        store, run_id, client = await _client(
            ScriptedReply(kind=CallKind.SYNTHESIZE, content='{"value":"zq7731"}')
        )
        with capture_spans() as exporter:
            await client.generate(_call())
        span = next(
            s for s in exporter.get_finished_spans() if s.name == "llm.synthesize"
        )
        record = (await store.list_llm_calls(run_id))[0].record

        assert record.trace_id == format(span.context.trace_id, "032x")
        assert record.span_id == format(span.context.span_id, "016x")

    asyncio.run(exercise())


def test_synthesis_and_verify_spans_nest() -> None:
    async def exercise() -> None:
        with capture_spans() as exporter:
            _store, _run_id, result = await _verified_answer()
        spans = {span.name: span for span in exporter.get_finished_spans()}
        synthesis = spans["llm.synthesize"]
        verify = spans[SPAN_VERIFY]
        synth = spans[SPAN_SYNTHESIZE]
        answer_node = spans["node.answer"]

        assert (
            synthesis.parent is not None
            and synthesis.parent.span_id == synth.context.span_id
        )
        assert (
            verify.parent is not None and verify.parent.span_id == synth.context.span_id
        )
        assert (
            synth.parent is not None
            and synth.parent.span_id == answer_node.context.span_id
        )
        assert len(result.claims) == 1
        assert (synth.attributes or {})[ATTR_CLAIMS_DRAFTED] == 1

    asyncio.run(exercise())


def test_verify_span_counts_match_usage() -> None:
    async def exercise() -> None:
        with capture_spans() as exporter:
            _store, _run_id, result = await _verified_answer()
        verify = next(
            span for span in exporter.get_finished_spans() if span.name == SPAN_VERIFY
        )
        attributes = verify.attributes or {}

        assert attributes[ATTR_CLAIMS_KEPT] == len(result.claims)
        assert attributes[ATTR_CLAIMS_REJECTED] == result.rejected_claims
        assert attributes[ATTR_CLAIMS_UNSUPPORTED] == result.unsupported_claims

    asyncio.run(exercise())
