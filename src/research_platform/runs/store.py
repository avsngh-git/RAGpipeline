"""Framework-independent contract for research run persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimResult,
    FailureCategory,
    PaperSummary,
    ResearchRequest,
    ResearchRunView,
    RunProvenance,
    RunStatus,
    RunUsage,
)
from research_platform.runs.repository import EvidenceRecord, StoredRun, ToolCallRecord


class RunStore(Protocol):
    """Async interface shared by the PostgreSQL and in-memory run stores."""

    async def create_run(
        self, request: ResearchRequest, *, generation: int | None = None
    ) -> UUID: ...

    async def get_run(self, run_id: UUID) -> StoredRun: ...

    async def list_runs(
        self, statuses: Sequence[RunStatus], *, limit: int = 100
    ) -> tuple[StoredRun, ...]: ...

    async def mark_running(
        self, run_id: UUID, *, provenance: RunProvenance
    ) -> None: ...

    async def record_resume(self, run_id: UUID) -> int: ...

    async def add_active_seconds(self, run_id: UUID, seconds: float) -> float: ...

    async def append_tool_call(self, run_id: UUID, record: ToolCallRecord) -> None: ...

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
    ) -> None: ...

    async def fail_run(
        self,
        run_id: UUID,
        *,
        category: FailureCategory,
        message: str,
        usage: RunUsage,
    ) -> None: ...

    async def get_run_view(self, run_id: UUID) -> ResearchRunView: ...

    async def prune(self, *, older_than: timedelta) -> tuple[UUID, ...]: ...
