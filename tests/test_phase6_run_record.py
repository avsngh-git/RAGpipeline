"""Owner-scoped run record and model-call text routes."""

from __future__ import annotations

import asyncio
from datetime import UTC
from uuid import UUID

import httpx
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.api.auth import AuthMode, AuthSettings
from research_platform.api.research_routes import ResearchAPIServices
from research_platform.auth.keys import InMemoryApiKeyStore, Scope
from research_platform.config import Settings
from research_platform.llm.contracts import ChatMessage
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimVerdict,
    DraftClaimOutcome,
    ResearchMode,
    ResearchRequest,
    RunBudgets,
    RunProvenance,
    RunUsage,
    SynthesisSummary,
)
from research_platform.runs.llm_records import LLMCallPayload, LLMCallRecord
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.repository import ToolCallRecord
from research_platform.runs.runner import ServingIdentity
from research_platform.services.readiness import ReadinessReport

_SNAPSHOT = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


class StubExecutor:
    async def submit(self, _run_id: UUID, *, request_id: str | None = None) -> None:
        return None


class RecordingStore(InMemoryRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.payload_requests: list[bool] = []

    async def list_llm_calls(self, run_id: UUID, *, include_payloads: bool = False):  # type: ignore[no-untyped-def]
        self.payload_requests.append(include_payloads)
        return await super().list_llm_calls(run_id, include_payloads=include_payloads)


def _app(
    store: InMemoryRunStore,
    *,
    settings: Settings | None = None,
    api_key_store: InMemoryApiKeyStore | None = None,
    auth_mode: AuthMode = "api_key",
) -> FastAPI:
    return create_app(
        settings=settings
        or Settings(
            environment="test",
            database_url="postgresql://test:test@localhost:5432/research_test",
            qdrant_url="http://localhost:26333",
        ),
        dependency_checker=StubReadinessChecker(),
        research_services=ResearchAPIServices(
            store=store,
            executor=StubExecutor(),  # type: ignore[arg-type]
            serving=ServingIdentity(_SNAPSHOT, "profile-v1"),
        ),
        auth_settings=AuthSettings(mode=auth_mode, bind_host="127.0.0.1"),
        api_key_store=api_key_store,
    )


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    key: str | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    headers = {} if key is None else {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers)


async def _keys() -> tuple[InMemoryApiKeyStore, dict[str, str]]:
    store = InMemoryApiKeyStore()
    _, alice = await store.create("alice", (Scope.RESEARCH, Scope.READ))
    _, bob = await store.create("bob", (Scope.RESEARCH, Scope.READ))
    _, ops = await store.create("ops", (Scope.ADMIN,))
    _, alice_research_only = await store.create("alice", (Scope.RESEARCH,))
    return store, {
        "alice": alice,
        "alice_research_only": alice_research_only,
        "bob": bob,
        "ops": ops,
    }


async def _run_with_record(store: InMemoryRunStore) -> UUID:
    run_id = await store.create_run(
        ResearchRequest(question="Synthetic zq7731 question", mode=ResearchMode.QUICK),
        principal="alice",
    )
    await store.mark_running(
        run_id,
        provenance=RunProvenance(
            snapshot_id=_SNAPSHOT,
            retrieval_profile_id="profile-v1",
            configuration_id=f"sha256:{'b' * 64}",
            code_revision="synthetic",
            model=ModelIdentity(
                name="synthetic-model", runtime="test", context_tokens=4096
            ),
            thinking={CallKind.PLAN: False},
            prompt_versions={"system": "synthetic-v1"},
            budgets=RunBudgets(),
            trace_id="synthetic-trace",
        ),
    )
    await store.append_tool_call(
        run_id,
        ToolCallRecord(
            ordinal=1,
            tool_name="search_papers",
            arguments={"query": "zq7731"},
            status="succeeded",
            result_summary={"count": 1},
            duration_ms=12.5,
        ),
    )
    await store.append_tool_call(
        run_id,
        ToolCallRecord(
            ordinal=2,
            tool_name="search_papers",
            arguments={"query": "zq7731"},
            status="cached",
            result_summary={"count": 1},
            duration_ms=0.1,
        ),
    )
    record = LLMCallRecord(
        kind=CallKind.SYNTHESIZE,
        status="succeeded",
        model_name="synthetic-model",
        think=True,
        attempts=1,
        duration_ms=4.0,
        prompt_version="synthetic-v1",
    )
    await store.append_llm_call(
        run_id,
        record,
        LLMCallPayload(
            messages=(ChatMessage("user", "Synthetic zq7731 prompt"),),
            thinking="Synthetic zq7731 thought",
            output="Synthetic zq7731 output",
        ),
    )
    await store.append_llm_call(run_id, record)
    await store.complete_run(
        run_id,
        answer="Synthetic zq7731 answer",
        outcome=AnswerOutcome.PARTIALLY_SUPPORTED,
        claims=(),
        usage=RunUsage(),
        drafts=(
            DraftClaimOutcome(
                ordinal=1,
                handle="E1",
                quote="Synthetic zq7731 quote",
                text="Synthetic zq7731 claim",
                verdict=ClaimVerdict.KEPT,
            ),
            DraftClaimOutcome(
                ordinal=2,
                handle="E2",
                quote="Synthetic zq7731 quote",
                text="Synthetic zq7731 rejected claim",
                verdict=ClaimVerdict.FAILED_CHECKS,
                failed_checks=("synthetic_check",),
            ),
        ),
        synthesis=SynthesisSummary(model_declared_insufficient=False, drafted=2),
    )
    return run_id


def test_record_returns_calls_drafts_and_diagnosis() -> None:
    async def exercise():
        key_store, keys = await _keys()
        store = InMemoryRunStore()
        run_id = await _run_with_record(store)
        response = await _request(
            _app(store, api_key_store=key_store),
            "GET",
            f"/v1/research/{run_id}/record",
            key=keys["alice"],
        )
        return response

    response = asyncio.run(exercise())
    assert response.status_code == 200
    body = response.json()
    assert [call["ordinal"] for call in body["tool_calls"]] == [1, 2]
    assert all(call["recorded_at"] is not None for call in body["tool_calls"])
    assert [call["text_recorded"] for call in body["model_calls"]] == [True, False]
    assert [claim["verdict"] for claim in body["drafted_claims"]] == [
        "kept",
        "failed_checks",
    ]
    assert body["diagnosis"]["run_id"] == body["run_id"]
    assert body["diagnosis"]["stage"] in {
        "none",
        "in_progress",
        "model",
        "planning",
        "retrieval",
        "evidence",
        "generation",
        "verification",
        "budget",
        "ingestion",
        "infrastructure",
    }


def test_record_hides_other_principals_runs() -> None:
    async def exercise():
        key_store, keys = await _keys()
        store = InMemoryRunStore()
        run_id = await _run_with_record(store)
        app = _app(store, api_key_store=key_store)
        bob = await _request(
            app, "GET", f"/v1/research/{run_id}/record", key=keys["bob"]
        )
        ops = await _request(
            app, "GET", f"/v1/research/{run_id}/record", key=keys["ops"]
        )
        return bob, ops

    bob, ops = asyncio.run(exercise())
    assert bob.status_code == 404
    assert bob.json()["error"]["code"] == "run_not_found"
    assert ops.status_code == 200


def test_record_requires_read_scope() -> None:
    async def exercise():
        key_store, keys = await _keys()
        store = InMemoryRunStore()
        run_id = await _run_with_record(store)
        return await _request(
            _app(store, api_key_store=key_store),
            "GET",
            f"/v1/research/{run_id}/record",
            key=keys["alice_research_only"],
        )

    assert asyncio.run(exercise()).status_code == 403


def test_model_text_available_under_trusted_profile() -> None:
    async def exercise():
        key_store, keys = await _keys()
        store = InMemoryRunStore()
        run_id = await _run_with_record(store)
        settings = Settings(
            environment="test",
            database_url="postgresql://test:test@localhost:5432/research_test",
            qdrant_url="http://localhost:26333",
            evidence_access_profile="trusted_private_local",
        )
        return await _request(
            _app(store, settings=settings, api_key_store=key_store),
            "GET",
            f"/v1/research/{run_id}/model-calls/1",
            key=keys["alice"],
        )

    body = asyncio.run(exercise()).json()
    assert body["state"] == "available"
    assert body["messages"] == [{"role": "user", "content": "Synthetic zq7731 prompt"}]
    assert body["thinking"] == "Synthetic zq7731 thought"
    assert body["output"] == "Synthetic zq7731 output"


def test_model_text_not_recorded() -> None:
    async def exercise():
        key_store, keys = await _keys()
        store = InMemoryRunStore()
        run_id = await _run_with_record(store)
        settings = Settings(
            environment="test",
            database_url="postgresql://test:test@localhost:5432/research_test",
            qdrant_url="http://localhost:26333",
            evidence_access_profile="trusted_private_local",
        )
        return await _request(
            _app(store, settings=settings, api_key_store=key_store),
            "GET",
            f"/v1/research/{run_id}/model-calls/2",
            key=keys["alice"],
        )

    body = asyncio.run(exercise()).json()
    assert body["state"] == "not_recorded"
    assert body["messages"] == []
    assert body["thinking"] is body["output"] is body["error_preview"] is None


def test_model_text_withheld_without_trusted_profile() -> None:
    async def exercise():
        key_store, keys = await _keys()
        store = RecordingStore()
        run_id = await _run_with_record(store)
        store.payload_requests.clear()
        response = await _request(
            _app(store, api_key_store=key_store),
            "GET",
            f"/v1/research/{run_id}/model-calls/1",
            key=keys["alice"],
        )
        return response, store.payload_requests

    response, payload_requests = asyncio.run(exercise())
    assert response.json()["state"] == "withheld"
    assert response.json()["messages"] == []
    assert True not in payload_requests


def test_model_text_unknown_ordinal_is_404() -> None:
    async def exercise():
        key_store, keys = await _keys()
        store = InMemoryRunStore()
        run_id = await _run_with_record(store)
        app = _app(store, api_key_store=key_store)
        missing = await _request(
            app,
            "GET",
            f"/v1/research/{run_id}/model-calls/9",
            key=keys["alice"],
        )
        invalid = await _request(
            app,
            "GET",
            f"/v1/research/{run_id}/model-calls/0",
            key=keys["alice"],
        )
        return missing, invalid

    missing, invalid = asyncio.run(exercise())
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "model_call_not_found"
    assert invalid.status_code == 422


def test_record_equality_ignores_recorded_at() -> None:
    from datetime import datetime

    first = ToolCallRecord(1, "search", {}, "cached", {}, 1.0)
    second = ToolCallRecord(
        1,
        "search",
        {},
        "cached",
        {},
        1.0,
        recorded_at=datetime(2026, 10, 23, tzinfo=UTC),
    )
    assert first == second
