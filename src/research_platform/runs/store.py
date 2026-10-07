"""Framework-independent contract for research run persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimResult,
    DraftClaimOutcome,
    FailureCategory,
    PaperSummary,
    ResearchRequest,
    ResearchRunView,
    RunProvenance,
    RunStatus,
    RunUsage,
    SynthesisSummary,
)
from research_platform.runs.llm_records import (
    LLMCallPayload,
    LLMCallRecord,
    StoredLLMCall,
)
from research_platform.runs.repository import EvidenceRecord, StoredRun, ToolCallRecord


class RunStore(Protocol):
    """Async interface shared by the PostgreSQL and in-memory run stores."""

    async def create_run(
        self,
        request: ResearchRequest,
        *,
        generation: int | None = None,
        principal: str = "legacy-local",
    ) -> UUID: ...

    async def get_run(self, run_id: UUID) -> StoredRun: ...

    async def count_active_runs(self, principal: str) -> int: ...

    async def list_runs(
        self, statuses: Sequence[RunStatus], *, limit: int = 100
    ) -> tuple[StoredRun, ...]: ...

    async def mark_running(
        self, run_id: UUID, *, provenance: RunProvenance
    ) -> None: ...

    async def record_resume(self, run_id: UUID) -> int: ...

    async def add_active_seconds(self, run_id: UUID, seconds: float) -> float: ...

    async def mark_waiting(self, run_id: UUID) -> None: ...

    async def mark_resumed_from_wait(self, run_id: UUID) -> None: ...

    async def switch_generation(
        self,
        run_id: UUID,
        *,
        generation: int,
        snapshot_id: UUID,
        record: ToolCallRecord,
    ) -> None: ...

    async def append_tool_call(self, run_id: UUID, record: ToolCallRecord) -> None: ...

    async def list_tool_calls(self, run_id: UUID) -> tuple[ToolCallRecord, ...]: ...

    async def append_llm_call(
        self,
        run_id: UUID,
        record: LLMCallRecord,
        payload: LLMCallPayload | None = None,
    ) -> int: ...

    async def list_llm_calls(
        self, run_id: UUID, *, include_payloads: bool = False
    ) -> tuple[StoredLLMCall, ...]: ...

    async def save_evidence(
        self, run_id: UUID, records: Sequence[EvidenceRecord]
    ) -> None: ...

    async def load_evidence(
        self, run_id: UUID, handles: Sequence[str] | None = None
    ) -> dict[str, EvidenceRecord]: ...

    async def save_uningested_candidates(
        self,
        run_id: UUID,
        candidates: Sequence[PaperSummary],
        *,
        minimum_similarity: float,
    ) -> None: ...

    async def complete_run(
        self,
        run_id: UUID,
        *,
        answer: str,
        outcome: AnswerOutcome,
        claims: Sequence[ClaimResult],
        usage: RunUsage,
        drafts: Sequence[DraftClaimOutcome] = (),
        synthesis: SynthesisSummary | None = None,
    ) -> None: ...

    async def list_draft_claims(
        self, run_id: UUID
    ) -> tuple[DraftClaimOutcome, ...]: ...

    async def get_synthesis_summary(self, run_id: UUID) -> SynthesisSummary | None: ...

    async def fail_run(
        self,
        run_id: UUID,
        *,
        category: FailureCategory,
        message: str,
        usage: RunUsage,
    ) -> None: ...

    async def get_run_view(self, run_id: UUID) -> ResearchRunView: ...

    async def save_run_configuration(
        self,
        configuration_id: str,
        configuration: Mapping[str, object],
        *,
        provenance_version: int,
    ) -> None: ...

    async def load_run_configuration(
        self, configuration_id: str
    ) -> dict[str, object]: ...

    async def prune(self, *, older_than: timedelta) -> tuple[UUID, ...]: ...
