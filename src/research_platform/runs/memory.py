"""In-memory implementation of the research run store contract."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

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
    configuration_id,
)
from research_platform.runs.llm_records import (
    LLMCallPayload,
    LLMCallRecord,
    StoredLLMCall,
)
from research_platform.runs.repository import (
    ConfigurationMismatch,
    ConfigurationNotFound,
    EvidenceRecord,
    InvalidRunTransition,
    RunNotFound,
    StoredRun,
    ToolCallRecord,
)


class InMemoryRunStore:
    """Dictionary-backed run store with PostgreSQL-equivalent transitions."""

    def __init__(self) -> None:
        self._runs: dict[UUID, StoredRun] = {}
        self._provenance: dict[UUID, RunProvenance] = {}
        self._answers: dict[UUID, tuple[str, AnswerOutcome, RunUsage]] = {}
        self._failures: dict[UUID, tuple[FailureCategory, str, RunUsage]] = {}
        self._claims: dict[UUID, tuple[ClaimResult, ...]] = {}
        self._tool_calls: dict[UUID, dict[int, ToolCallRecord]] = {}
        self._evidence: dict[UUID, dict[str, EvidenceRecord]] = {}
        self.generations: dict[UUID, int | None] = {}
        self._configurations: dict[str, dict[str, object]] = {}
        self._llm_calls: dict[UUID, list[StoredLLMCall]] = {}
        self._drafts: dict[UUID, tuple[DraftClaimOutcome, ...]] = {}
        self._synthesis: dict[UUID, SynthesisSummary] = {}

    async def create_run(
        self, request: ResearchRequest, *, generation: int | None = None
    ) -> UUID:
        run_id = uuid4()
        self._runs[run_id] = StoredRun(
            run_id=run_id,
            status=RunStatus.QUEUED,
            mode=request.mode,
            request=request,
            snapshot_id=request.snapshot_id,
            configuration_id=None,
            resume_count=0,
            active_seconds=0.0,
            created_at=datetime.now(UTC),
            started_at=None,
            completed_at=None,
        )
        self.generations[run_id] = generation
        return run_id

    async def get_run(self, run_id: UUID) -> StoredRun:
        return self._get_run(run_id)

    async def list_runs(
        self, statuses: Sequence[RunStatus], *, limit: int = 100
    ) -> tuple[StoredRun, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if any(not isinstance(status, RunStatus) for status in statuses):
            raise ValueError("statuses must contain RunStatus values")
        selected = set(statuses)
        runs = sorted(
            (run for run in self._runs.values() if run.status in selected),
            key=lambda run: (run.created_at, run.run_id),
            reverse=True,
        )
        return tuple(runs[:limit])

    async def mark_running(self, run_id: UUID, *, provenance: RunProvenance) -> None:
        run = self._get_run(run_id)
        if run.status not in (
            RunStatus.QUEUED,
            RunStatus.RUNNING,
            RunStatus.WAITING_FOR_INGESTION,
        ):
            raise InvalidRunTransition(
                f"cannot mark running run {run_id} from status {run.status.value}"
            )
        self._runs[run_id] = replace(
            run,
            status=RunStatus.RUNNING,
            snapshot_id=(
                provenance.snapshot_id
                if run.status is RunStatus.QUEUED or run.snapshot_id is None
                else run.snapshot_id
            ),
            configuration_id=provenance.configuration_id,
            generation=(
                (
                    provenance.generation
                    if provenance.generation is not None
                    else self.generations.get(run_id)
                )
                if run.status is RunStatus.QUEUED
                else run.generation
            ),
            pinned_snapshot_id=run.pinned_snapshot_id or provenance.snapshot_id,
            pinned_generation=(
                run.pinned_generation
                if run.pinned_snapshot_id is not None
                else provenance.generation
            ),
            started_at=run.started_at or datetime.now(UTC),
        )
        previous = self._provenance.get(run_id)
        if run.status is not RunStatus.QUEUED and previous is not None:
            provenance = provenance.model_copy(
                update={
                    "uningested_candidates": previous.uningested_candidates,
                    "uningested_similarity_threshold": previous.uningested_similarity_threshold,
                }
            )
        self._provenance[run_id] = provenance

    async def record_resume(self, run_id: UUID) -> int:
        run = self._running(run_id, "record resume")
        updated = run.resume_count + 1
        self._runs[run_id] = replace(run, resume_count=updated)
        return updated

    async def add_active_seconds(self, run_id: UUID, seconds: float) -> float:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("seconds must be finite and non-negative")
        run = self._running(run_id, "add active time")
        total = run.active_seconds + seconds
        self._runs[run_id] = replace(run, active_seconds=total)
        return total

    async def mark_waiting(self, run_id: UUID) -> None:
        run = self._get_run(run_id)
        if run.status not in (RunStatus.RUNNING, RunStatus.WAITING_FOR_INGESTION):
            raise InvalidRunTransition(
                f"cannot mark waiting run {run_id} from status {run.status.value}"
            )
        self._runs[run_id] = replace(run, status=RunStatus.WAITING_FOR_INGESTION)

    async def mark_resumed_from_wait(self, run_id: UUID) -> None:
        run = self._get_run(run_id)
        if run.status not in (RunStatus.RUNNING, RunStatus.WAITING_FOR_INGESTION):
            raise InvalidRunTransition(
                f"cannot resume run {run_id} from status {run.status.value}"
            )
        self._runs[run_id] = replace(run, status=RunStatus.RUNNING)

    async def switch_generation(
        self,
        run_id: UUID,
        *,
        generation: int,
        snapshot_id: UUID,
        record: ToolCallRecord,
    ) -> None:
        run = self._get_run(run_id)
        if run.status not in (RunStatus.RUNNING, RunStatus.WAITING_FOR_INGESTION):
            raise InvalidRunTransition(
                f"cannot switch generation of run {run_id} from {run.status.value}"
            )
        self._runs[run_id] = replace(
            run, generation=generation, snapshot_id=snapshot_id
        )
        self.generations[run_id] = generation
        await self.append_tool_call(run_id, record)

    def tool_calls(self, run_id: UUID) -> tuple[ToolCallRecord, ...]:
        """Recorded tool calls in ordinal order (test inspection)."""
        calls = self._tool_calls.get(run_id, {})
        return tuple(calls[ordinal] for ordinal in sorted(calls))

    async def append_tool_call(self, run_id: UUID, record: ToolCallRecord) -> None:
        if record.ordinal < 0:
            raise ValueError("ordinal must be non-negative")
        if not record.tool_name.strip():
            raise ValueError("tool_name must be non-empty")
        _nonnegative_finite(record.duration_ms, "duration_ms")
        self._get_run(run_id)
        calls = self._tool_calls.setdefault(run_id, {})
        calls.setdefault(record.ordinal, record)

    async def append_llm_call(
        self,
        run_id: UUID,
        record: LLMCallRecord,
        payload: LLMCallPayload | None = None,
    ) -> int:
        self._get_run(run_id)
        calls = self._llm_calls.setdefault(run_id, [])
        ordinal = len(calls) + 1
        calls.append(StoredLLMCall(ordinal=ordinal, record=record, payload=payload))
        return ordinal

    async def list_llm_calls(
        self, run_id: UUID, *, include_payloads: bool = False
    ) -> tuple[StoredLLMCall, ...]:
        self._get_run(run_id)
        calls = self._llm_calls.get(run_id, [])
        if include_payloads:
            return tuple(calls)
        return tuple(replace(call, payload=None) for call in calls)

    async def save_evidence(
        self, run_id: UUID, records: Sequence[EvidenceRecord]
    ) -> None:
        if not records:
            return
        self._get_run(run_id)
        evidence = self._evidence.setdefault(run_id, {})
        chunks = {record.chunk_id for record in evidence.values()}
        for record in records:
            if record.handle in evidence or record.chunk_id in chunks:
                continue
            evidence[record.handle] = record
            chunks.add(record.chunk_id)

    async def load_evidence(
        self, run_id: UUID, handles: Sequence[str] | None = None
    ) -> dict[str, EvidenceRecord]:
        evidence = self._evidence.get(run_id, {})
        if handles is None:
            return dict(evidence)
        requested = set(handles)
        return {
            handle: record for handle, record in evidence.items() if handle in requested
        }

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
    ) -> None:
        run = self._running(run_id, "complete")
        _validate_claim_evidence(self._evidence.get(run_id, {}), claims)
        self._claims[run_id] = tuple(claims)
        self._drafts[run_id] = tuple(drafts)
        if synthesis is None:
            self._synthesis.pop(run_id, None)
        else:
            self._synthesis[run_id] = synthesis
        self._answers[run_id] = (answer, outcome, usage)
        self._failures.pop(run_id, None)
        self._runs[run_id] = replace(
            run, status=RunStatus.COMPLETED, completed_at=datetime.now(UTC)
        )

    async def list_draft_claims(self, run_id: UUID) -> tuple[DraftClaimOutcome, ...]:
        return self._drafts.get(run_id, ())

    async def get_synthesis_summary(self, run_id: UUID) -> SynthesisSummary | None:
        return self._synthesis.get(run_id)

    async def fail_run(
        self,
        run_id: UUID,
        *,
        category: FailureCategory,
        message: str,
        usage: RunUsage,
    ) -> None:
        run = self._get_run(run_id)
        if run.status not in (
            RunStatus.QUEUED,
            RunStatus.RUNNING,
            RunStatus.WAITING_FOR_INGESTION,
        ):
            raise InvalidRunTransition(
                f"cannot fail run {run_id} from status {run.status.value}"
            )
        self._failures[run_id] = (category, message[:500], usage)
        self._answers.pop(run_id, None)
        self._runs[run_id] = replace(
            run, status=RunStatus.FAILED, completed_at=datetime.now(UTC)
        )

    async def save_uningested_candidates(
        self,
        run_id: UUID,
        candidates: Sequence[PaperSummary],
        *,
        minimum_similarity: float,
    ) -> None:
        """Store the same catalog diagnostic as the PostgreSQL run store."""
        self._running(run_id, "save uningested candidates")
        if not math.isfinite(minimum_similarity) or not -1 <= minimum_similarity <= 1:
            raise ValueError("minimum_similarity must be finite and between -1 and 1")
        if len(candidates) > 5:
            raise ValueError("at most five uningested candidates may be stored")
        self._provenance[run_id] = self._provenance[run_id].model_copy(
            update={
                "uningested_candidates": tuple(candidates),
                "uningested_similarity_threshold": minimum_similarity,
            }
        )

    async def get_run_view(self, run_id: UUID) -> ResearchRunView:
        run = self._get_run(run_id)
        answer = self._answers.get(run_id)
        failure = self._failures.get(run_id)
        claims = self._claims.get(run_id, ())
        papers: dict[str, PaperSummary] = {}
        evidence = self._evidence.get(run_id, {})
        for claim in claims:
            for citation in claim.evidence:
                record = evidence.get(citation.handle)
                if record is None:
                    continue
                papers.setdefault(
                    record.paper_id,
                    PaperSummary(
                        paper_id=record.paper_id,
                        title=_optional_string(record.metadata.get("title")),
                        publication_year=_optional_int(
                            record.metadata.get("publication_year")
                        ),
                    ),
                )
        provenance = self._provenance.get(run_id)
        return ResearchRunView(
            run_id=run_id,
            status=run.status,
            mode=run.mode,
            question=run.request.question,
            answer=answer[0] if answer else None,
            answer_outcome=answer[1] if answer else None,
            claims=claims,
            papers=tuple(papers.values()),
            uningested_candidates=provenance.uningested_candidates
            if provenance
            else (),
            failure_category=failure[0] if failure else None,
            error_message=failure[1] if failure else None,
            provenance=provenance,
            generation=run.generation,
            usage=(
                answer[2]
                if answer
                else failure[2]
                if failure
                else RunUsage.model_construct()
            ),
            created_at=run.created_at,
            completed_at=run.completed_at,
        )

    async def save_run_configuration(
        self,
        configuration_id: str,
        configuration: Mapping[str, object],
        *,
        provenance_version: int,
    ) -> None:
        if _hash(configuration) != configuration_id:
            raise ValueError("configuration_id does not match the configuration")
        if provenance_version < 1:
            raise ValueError("provenance_version must be at least 1")
        stored = self._configurations.setdefault(
            configuration_id, _json_copy(configuration)
        )
        if _hash(stored) != configuration_id:
            raise ConfigurationMismatch(configuration_id)

    async def load_run_configuration(self, configuration_id: str) -> dict[str, object]:
        try:
            return _json_copy(self._configurations[configuration_id])
        except KeyError:
            raise ConfigurationNotFound(configuration_id) from None

    async def prune(self, *, older_than: timedelta) -> tuple[UUID, ...]:
        if older_than <= timedelta(0):
            raise ValueError("older_than must be positive")
        cutoff = datetime.now(UTC) - older_than
        removed = tuple(
            run_id
            for run_id, run in self._runs.items()
            if run.status in (RunStatus.COMPLETED, RunStatus.FAILED)
            and run.completed_at is not None
            and run.completed_at < cutoff
        )
        for run_id in removed:
            self._runs.pop(run_id, None)
            self._provenance.pop(run_id, None)
            self._answers.pop(run_id, None)
            self._failures.pop(run_id, None)
            self._claims.pop(run_id, None)
            self._tool_calls.pop(run_id, None)
            self._evidence.pop(run_id, None)
            self._llm_calls.pop(run_id, None)
            self._drafts.pop(run_id, None)
            self._synthesis.pop(run_id, None)
        return removed

    def _get_run(self, run_id: UUID) -> StoredRun:
        try:
            return self._runs[run_id]
        except KeyError:
            raise RunNotFound(f"run {run_id} was not found") from None

    def _running(self, run_id: UUID, operation: str) -> StoredRun:
        run = self._get_run(run_id)
        if run.status not in (RunStatus.RUNNING, RunStatus.WAITING_FOR_INGESTION):
            raise InvalidRunTransition(
                f"cannot {operation} run {run_id} from status {run.status.value}"
            )
        return run


def _validate_claim_evidence(
    evidence: dict[str, EvidenceRecord], claims: Sequence[ClaimResult]
) -> None:
    requested: dict[str, tuple[str, str]] = {}
    for claim in claims:
        for citation in claim.evidence:
            identity = (citation.chunk_id, citation.paper_id)
            previous = requested.setdefault(citation.handle, identity)
            if previous != identity:
                raise ValueError(
                    "one evidence handle cannot identify multiple passages"
                )
    if any(
        handle not in evidence
        or (evidence[handle].chunk_id, evidence[handle].paper_id) != identity
        for handle, identity in requested.items()
    ):
        raise ValueError("claim evidence must match evidence stored for this run")


def _hash(configuration: Mapping[str, object]) -> str:
    return configuration_id(configuration)


def _json_copy(configuration: Mapping[str, object]) -> dict[str, object]:
    copied = json.loads(json.dumps(configuration, sort_keys=True, default=str))
    if not isinstance(copied, dict):
        raise ValueError("configuration must be a JSON object")
    return copied


def _nonnegative_finite(value: float, name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
