"""Synthetic research runs for Playwright UI journeys."""

from __future__ import annotations

import asyncio
from uuid import UUID

from research_platform.llm.contracts import ChatMessage
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimResult,
    ClaimVerdict,
    DraftClaimOutcome,
    EvidenceCitation,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunProvenance,
    RunUsage,
    SupportLabel,
    SynthesisSummary,
)
from research_platform.runs.llm_records import LLMCallPayload, LLMCallRecord
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.repository import EvidenceRecord, ToolCallRecord

_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000001")
_PROFILE_ID = "sha256:" + "a" * 64
_CONFIGURATION_ID = "sha256:" + "b" * 64
_PAPER_ID = "W100"
_PAPER_TITLE = "Retrieval paper A"
_EVIDENCE_TEXT = "zq7731 supports the synthetic finding."
_QUOTE = "zq7731 supports the synthetic finding."
_CLAIM = "zq7731 supports the finding."


class ScriptedExecutor:
    """Submit plays a short scripted run; cancel stops it like RunExecutor.cancel."""

    def __init__(self, store: InMemoryRunStore, *, step_seconds: float = 0.3) -> None:
        self.store = store
        self.step_seconds = step_seconds
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    async def submit(self, run_id: UUID, *, request_id: str | None = None) -> None:
        del request_id
        self._tasks[run_id] = asyncio.create_task(self._play(run_id))

    async def cancel(self, run_id: UUID) -> None:
        task = self._tasks.get(run_id)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _play(self, run_id: UUID) -> None:
        await _mark_running(self.store, run_id)
        await self.store.append_tool_call(
            run_id,
            ToolCallRecord(
                ordinal=1,
                tool_name="search_papers",
                arguments={"query": "zq7731"},
                status="succeeded",
                result_summary={"papers": 2},
                duration_ms=4.0,
            ),
        )
        await asyncio.sleep(self.step_seconds)
        await _append_model_call(self.store, run_id, CallKind.PLAN, payload=True)
        await asyncio.sleep(self.step_seconds)
        await self.store.append_tool_call(
            run_id,
            ToolCallRecord(
                ordinal=2,
                tool_name="search_evidence",
                arguments={"query": "zq7731"},
                status="succeeded",
                result_summary={"passages": 2},
                duration_ms=5.0,
            ),
        )
        await asyncio.sleep(self.step_seconds)
        await _append_model_call(self.store, run_id, CallKind.SYNTHESIZE, payload=True)
        await asyncio.sleep(self.step_seconds)
        await _finish_run(self.store, run_id)


async def seed_completed_run(store: InMemoryRunStore, principal: str) -> UUID:
    """Write a completed synthetic run, including one call with no text payload."""
    run_id = await store.create_run(
        ResearchRequest(
            question="zq7731 seeded research question", mode=ResearchMode.QUICK
        ),
        principal=principal,
    )
    await _mark_running(store, run_id)
    await store.append_tool_call(
        run_id,
        ToolCallRecord(
            ordinal=1,
            tool_name="search_papers",
            arguments={"query": "zq7731"},
            status="succeeded",
            result_summary={"papers": 2},
            duration_ms=4.0,
        ),
    )
    await _append_model_call(store, run_id, CallKind.PLAN, payload=True)
    await store.append_tool_call(
        run_id,
        ToolCallRecord(
            ordinal=2,
            tool_name="search_evidence",
            arguments={"query": "zq7731"},
            status="succeeded",
            result_summary={"passages": 2},
            duration_ms=5.0,
        ),
    )
    await _append_model_call(store, run_id, CallKind.EVALUATE, payload=False)
    await _append_model_call(store, run_id, CallKind.SYNTHESIZE, payload=True)
    await _finish_run(store, run_id)
    return run_id


async def _mark_running(store: InMemoryRunStore, run_id: UUID) -> None:
    await store.mark_running(
        run_id,
        provenance=RunProvenance(
            snapshot_id=_SNAPSHOT_ID,
            retrieval_profile_id=_PROFILE_ID,
            configuration_id=_CONFIGURATION_ID,
            code_revision="browser-test",
            model=ModelIdentity(
                name="scripted-model", runtime="synthetic", context_tokens=8192
            ),
            thinking={CallKind.PLAN: False, CallKind.SYNTHESIZE: True},
            prompt_versions={"system": "zq7731-v1"},
            budgets=RunBudgets(),
            trace_id="zq7731-trace",
            generation=1,
        ),
    )


async def _append_model_call(
    store: InMemoryRunStore,
    run_id: UUID,
    kind: CallKind,
    *,
    payload: bool,
) -> None:
    record = LLMCallRecord(
        kind=kind,
        status="succeeded",
        model_name="scripted-model",
        think=kind is CallKind.SYNTHESIZE,
        attempts=1,
        duration_ms=6.0,
        prompt_tokens=12,
        output_tokens=7,
        thinking_chars=8 if kind is CallKind.SYNTHESIZE else 0,
        trace_id="zq7731-trace",
    )
    call_payload = (
        LLMCallPayload(
            messages=(
                ChatMessage("system", "zq7731 synthetic system instructions"),
                ChatMessage("user", "zq7731 synthetic research request"),
            ),
            thinking="zq7731 synthetic reasoning",
            output="zq7731 synthetic model output",
        )
        if payload
        else None
    )
    await store.append_llm_call(run_id, record, call_payload)


async def _finish_run(store: InMemoryRunStore, run_id: UUID) -> None:
    await store.save_evidence(
        run_id,
        (
            EvidenceRecord(
                handle="E1",
                chunk_id="zq7731-chunk-1",
                paper_id=_PAPER_ID,
                text=_EVIDENCE_TEXT,
                metadata={"title": _PAPER_TITLE, "publication_year": 2021},
            ),
            EvidenceRecord(
                handle="E2",
                chunk_id="zq7731-chunk-2",
                paper_id="W200",
                text="zq7731 second synthetic passage.",
                metadata={"title": "Retrieval paper B", "publication_year": 2023},
            ),
        ),
    )
    await store.complete_run(
        run_id,
        answer=f"{_CLAIM} [E1]",
        outcome=AnswerOutcome.PARTIALLY_SUPPORTED,
        claims=(
            ClaimResult(
                claim_id="claim-1",
                text=_CLAIM,
                quote=_QUOTE,
                evidence=(
                    EvidenceCitation(
                        handle="E1", chunk_id="zq7731-chunk-1", paper_id=_PAPER_ID
                    ),
                ),
                support=SupportLabel.SUPPORTED,
            ),
        ),
        usage=RunUsage(plan_rounds=1, tool_calls=2, model_calls=2, active_seconds=1.0),
        drafts=(
            DraftClaimOutcome(
                ordinal=1,
                handle="E1",
                quote=_QUOTE,
                text=_CLAIM,
                verdict=ClaimVerdict.KEPT,
                chunk_id="zq7731-chunk-1",
                paper_id=_PAPER_ID,
            ),
            DraftClaimOutcome(
                ordinal=2,
                handle="E2",
                quote="zq7731 unverified quote.",
                text="zq7731 unsupported drafted claim.",
                verdict=ClaimVerdict.FAILED_CHECKS,
                failed_checks=("quote_found",),
                chunk_id="zq7731-chunk-2",
                paper_id="W200",
            ),
        ),
        synthesis=SynthesisSummary(
            model_declared_insufficient=False,
            relevant_handles=("E1", "E2"),
            packed_handles=("E1", "E2"),
            drafted=2,
        ),
    )
