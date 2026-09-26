"""Reusable sequential ingestion orchestration over injected stage processors."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from research_platform.ingestion.stage_repository import (
    _FAILURE_CATEGORY,
    IngestionJobRepository,
    JobStateError,
    StageAttempt,
)


@dataclass(frozen=True)
class IngestionDocument:
    document_id: UUID
    input_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, UUID):
            raise ValueError("document_id must be a UUID")
        _validate_sha256(self.input_fingerprint, "document input_fingerprint")


@dataclass(frozen=True)
class StageContext:
    job_id: UUID
    document_id: UUID
    stage: str
    configuration_id: str
    input_fingerprint: str
    upstream_references: Mapping[str, object]
    retry_reason: str | None


@dataclass(frozen=True)
class StageOutcome:
    output_fingerprint: str
    output_references: Mapping[str, object] = field(default_factory=dict)
    resource_measurements: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_sha256(self.output_fingerprint, "stage output_fingerprint")
        _validate_json_mapping(self.output_references, "output_references")
        _validate_json_mapping(self.resource_measurements, "resource_measurements")


class StageProcessor(Protocol):
    async def process(self, context: StageContext) -> StageOutcome: ...


@dataclass(frozen=True)
class PipelineStage:
    name: str
    configuration_id: str
    processor: StageProcessor


@dataclass(frozen=True)
class DocumentFailure:
    document_id: UUID
    stage: str
    category: str
    retryable: bool


@dataclass(frozen=True)
class IngestionRunReport:
    job_id: UUID
    status: str
    documents_completed: int
    documents_failed: int
    stages_run: int
    stages_reused: int
    failures: tuple[DocumentFailure, ...]


class DocumentStageFailure(RuntimeError):
    """A paper-specific error that should not stop the remaining documents."""

    def __init__(self, category: str, message: str, *, retryable: bool = True) -> None:
        if (
            not isinstance(category, str)
            or not _FAILURE_CATEGORY.fullmatch(category)
            or not isinstance(message, str)
            or not message.strip()
            or not isinstance(retryable, bool)
        ):
            raise ValueError(
                "document stage failures need a machine-readable category, message, "
                "and boolean retryable flag"
            )
        self.category = category
        self.retryable = retryable
        super().__init__(message)


class SharedPipelineFailure(RuntimeError):
    """A process-wide failure that should stop the current ingestion job."""

    def __init__(self, category: str, message: str, *, retryable: bool = True) -> None:
        if (
            not isinstance(category, str)
            or not _FAILURE_CATEGORY.fullmatch(category)
            or not isinstance(message, str)
            or not message.strip()
            or not isinstance(retryable, bool)
        ):
            raise ValueError(
                "shared pipeline failures need a machine-readable category, message, "
                "and boolean retryable flag"
            )
        self.category = category
        self.retryable = retryable
        super().__init__(message)


class IngestionExecutionError(RuntimeError):
    """Safe caller-facing pipeline failure without source-controlled details."""

    def __init__(self, category: str, *, retryable: bool) -> None:
        if not isinstance(category, str) or not _FAILURE_CATEGORY.fullmatch(category):
            raise ValueError("pipeline error needs a machine-readable category")
        if not isinstance(retryable, bool):
            raise ValueError("pipeline error retryable flag must be a boolean")
        self.category = category
        self.retryable = retryable
        super().__init__(f"ingestion stopped; failure_category={category}")


class IngestionRunner:
    """Resume unchanged stages, retry selected work and stop on shared failures."""

    def __init__(
        self,
        repository: IngestionJobRepository,
        *,
        lease_seconds: int = 300,
    ) -> None:
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int):
            raise ValueError("lease_seconds must be an integer")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._repository = repository
        self._lease_seconds = lease_seconds

    async def run(
        self,
        job_id: UUID,
        documents: Sequence[IngestionDocument],
        stages: Sequence[PipelineStage],
        *,
        selected_document_ids: Sequence[UUID] | None = None,
        from_stage: str | None = None,
        retry_reason: str | None = None,
    ) -> IngestionRunReport:
        _validate_plan(documents, stages)
        selected = _select_documents(documents, selected_document_ids)
        stage_names = [stage.name for stage in stages]
        if from_stage is not None:
            if from_stage not in stage_names:
                raise ValueError("from_stage is not in the configured pipeline")
        is_targeted = selected_document_ids is not None or from_stage is not None
        if retry_reason is not None and (
            not isinstance(retry_reason, str) or not retry_reason.strip()
        ):
            raise ValueError("retry_reason must be non-empty text or null")
        if is_targeted and retry_reason is None:
            raise ValueError("targeted retries require a non-empty retry_reason")
        retry_reason = retry_reason.strip() if retry_reason is not None else None

        await self._repository.record_plan(
            job_id,
            tuple(
                (document.document_id, document.input_fingerprint)
                for document in documents
            ),
            terminal_stage=stages[-1].name,
            terminal_configuration_id=stages[-1].configuration_id,
        )
        owner_token = await self._repository.claim(
            job_id, lease_seconds=self._lease_seconds
        )
        active_attempt: StageAttempt | None = None
        failures: list[DocumentFailure] = []
        stages_run = 0
        stages_reused = 0
        documents_completed = 0
        try:
            first_stage_index = stage_names.index(from_stage) if from_stage else 0
            for document in selected:
                fingerprint = document.input_fingerprint
                upstream_references: dict[str, object] = {}
                document_failed = False
                for stage_index, stage in enumerate(stages):
                    if stage_index < first_stage_index:
                        cached = await self._repository.completed_output(
                            job_id,
                            document.document_id,
                            stage=stage.name,
                            configuration_id=stage.configuration_id,
                            input_fingerprint=fingerprint,
                        )
                        if cached is None:
                            raise JobStateError(
                                f"cannot retry {from_stage}; prerequisite stage "
                                f"{stage.name} has no matching checkpoint"
                            )
                        fingerprint = _output_fingerprint(cached)
                        upstream_references.update(_references(cached))
                        stages_reused += 1
                        continue

                    force_this_stage = (
                        from_stage is not None and stage_index == first_stage_index
                    )
                    if not force_this_stage:
                        cached = await self._repository.completed_output(
                            job_id,
                            document.document_id,
                            stage=stage.name,
                            configuration_id=stage.configuration_id,
                            input_fingerprint=fingerprint,
                        )
                        if cached is not None:
                            fingerprint = _output_fingerprint(cached)
                            upstream_references.update(_references(cached))
                            stages_reused += 1
                            continue

                    await self._repository.heartbeat(
                        job_id, owner_token, lease_seconds=self._lease_seconds
                    )
                    active_attempt = await self._repository.start_attempt(
                        job_id,
                        owner_token,
                        document_id=document.document_id,
                        stage=stage.name,
                        configuration_id=stage.configuration_id,
                        input_fingerprint=fingerprint,
                        retry_reason=retry_reason if is_targeted else None,
                    )
                    context = StageContext(
                        job_id=job_id,
                        document_id=document.document_id,
                        stage=stage.name,
                        configuration_id=stage.configuration_id,
                        input_fingerprint=fingerprint,
                        upstream_references=dict(upstream_references),
                        retry_reason=retry_reason if is_targeted else None,
                    )
                    try:
                        outcome = await self._process_with_heartbeat(
                            job_id, owner_token, stage.processor, context
                        )
                        _validate_outcome(outcome)
                    except DocumentStageFailure as error:
                        await self._repository.finish_attempt(
                            active_attempt.id,
                            owner_token,
                            status="failed",
                            failure_category=error.category,
                            error_message=str(error),
                            retryable=error.retryable,
                        )
                        active_attempt = None
                        failures.append(
                            DocumentFailure(
                                document_id=document.document_id,
                                stage=stage.name,
                                category=error.category,
                                retryable=error.retryable,
                            )
                        )
                        document_failed = True
                        break

                    output_references = dict(outcome.output_references)
                    output_references["output_fingerprint"] = outcome.output_fingerprint
                    await self._repository.finish_attempt(
                        active_attempt.id,
                        owner_token,
                        status="completed",
                        output_references=output_references,
                        resource_measurements=outcome.resource_measurements,
                    )
                    active_attempt = None
                    upstream_references.update(dict(outcome.output_references))
                    fingerprint = outcome.output_fingerprint
                    stages_run += 1
                if document_failed:
                    continue
                documents_completed += 1

            summary = await self._repository.get_summary(job_id)
            plan_is_complete = await self._repository.plan_is_complete(job_id)
            final_status = (
                "completed"
                if not summary.failed_documents and plan_is_complete
                else "failed"
            )
            await self._repository.finish_job(
                job_id,
                owner_token,
                status=final_status,  # type: ignore[arg-type]
            )
            return IngestionRunReport(
                job_id=job_id,
                status=final_status,
                documents_completed=documents_completed,
                documents_failed=len(failures),
                stages_run=stages_run,
                stages_reused=stages_reused,
                failures=tuple(failures),
            )
        except asyncio.CancelledError:
            if active_attempt is not None:
                await self._repository.finish_attempt(
                    active_attempt.id,
                    owner_token,
                    status="failed",
                    failure_category="cancelled",
                    error_message="ingestion process was cancelled",
                    retryable=True,
                )
            await self._repository.finish_job(job_id, owner_token, status="cancelled")
            raise asyncio.CancelledError("ingestion process was cancelled") from None
        except Exception as error:
            category = (
                error.category
                if isinstance(error, SharedPipelineFailure)
                else _exception_category(error)
            )
            retryable = (
                error.retryable if isinstance(error, SharedPipelineFailure) else False
            )
            if active_attempt is not None:
                try:
                    await self._repository.finish_attempt(
                        active_attempt.id,
                        owner_token,
                        status="failed",
                        failure_category=category,
                        error_message=str(error),
                        retryable=retryable,
                    )
                except Exception:
                    pass
            try:
                await self._repository.finish_job(job_id, owner_token, status="failed")
            except Exception:
                pass
            raise IngestionExecutionError(category, retryable=retryable) from None

    async def _process_with_heartbeat(
        self,
        job_id: UUID,
        owner_token: UUID,
        processor: StageProcessor,
        context: StageContext,
    ) -> StageOutcome:
        task = asyncio.create_task(processor.process(context))
        wait_seconds = max(1, self._lease_seconds // 3)
        try:
            while True:
                done, _pending = await asyncio.wait(
                    (task,), timeout=wait_seconds, return_when=asyncio.FIRST_COMPLETED
                )
                if task in done:
                    return task.result()
                await self._repository.heartbeat(
                    job_id, owner_token, lease_seconds=self._lease_seconds
                )
        except BaseException:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise


def _validate_plan(
    documents: Sequence[IngestionDocument], stages: Sequence[PipelineStage]
) -> None:
    if not documents:
        raise ValueError("an ingestion run needs at least one document")
    if len({document.document_id for document in documents}) != len(documents):
        raise ValueError("an ingestion run cannot repeat a document")
    for document in documents:
        _validate_sha256(document.input_fingerprint, "document input_fingerprint")
    if not stages:
        raise ValueError("an ingestion run needs at least one stage")
    if len({stage.name for stage in stages}) != len(stages):
        raise ValueError("pipeline stage names must be unique")
    for stage in stages:
        if not isinstance(stage.name, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]{0,63}", stage.name
        ):
            raise ValueError("pipeline stage names must be lowercase identifiers")
        _validate_sha256(stage.configuration_id, "stage configuration_id")


def _exception_category(error: Exception) -> str:
    name = type(error).__name__
    category = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return category if _FAILURE_CATEGORY.fullmatch(category) else "unexpected_error"


def _select_documents(
    documents: Sequence[IngestionDocument],
    selected_document_ids: Sequence[UUID] | None,
) -> tuple[IngestionDocument, ...]:
    if selected_document_ids is None:
        return tuple(documents)
    if not selected_document_ids:
        raise ValueError("targeted retry needs at least one document ID")
    selected_ids = set(selected_document_ids)
    if len(selected_ids) != len(selected_document_ids):
        raise ValueError("targeted retry cannot repeat a document ID")
    by_id = {document.document_id: document for document in documents}
    if not selected_ids.issubset(by_id):
        raise ValueError("targeted retry includes a document outside the run plan")
    return tuple(
        document for document in documents if document.document_id in selected_ids
    )


def _validate_outcome(outcome: StageOutcome) -> None:
    if not isinstance(outcome, StageOutcome):
        raise ValueError("stage processor must return a StageOutcome")
    _validate_sha256(outcome.output_fingerprint, "stage output_fingerprint")


def _output_fingerprint(references: Mapping[str, object]) -> str:
    value = references.get("output_fingerprint")
    if not isinstance(value, str):
        raise JobStateError("completed stage checkpoint has no output fingerprint")
    _validate_sha256(value, "stage output_fingerprint")
    return value


def _references(references: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value for key, value in references.items() if key != "output_fingerprint"
    }


def _validate_sha256(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} must be a SHA-256 identity")


def _validate_json_mapping(value: Mapping[str, object], name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    try:
        json.dumps(dict(value), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must contain finite JSON-compatible values") from None
