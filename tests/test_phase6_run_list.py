"""Run-history API and cursor contracts."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.api.auth import AuthSettings
from research_platform.api.research_routes import ResearchAPIServices
from research_platform.auth.keys import InMemoryApiKeyStore, Scope
from research_platform.config import Settings
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.contracts import (
    AnswerOutcome,
    FailureCategory,
    ResearchRequest,
    RunBudgets,
    RunProvenance,
    RunUsage,
)
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.runner import ServingIdentity
from research_platform.services.errors import AppError
from research_platform.services.run_cursor import decode_run_cursor, encode_run_cursor

_SNAPSHOT = UUID("4b11fab3-d4a5-4e7a-a58e-8654accf2c6c")


class _Readiness:
    async def check(self):
        from research_platform.services.readiness import ReadinessReport

        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


class _Executor:
    async def submit(self, _run_id: UUID, *, request_id: str | None = None) -> None:
        return None


def _app(
    store: InMemoryRunStore,
    *,
    api_key_store: InMemoryApiKeyStore,
    llm_available=None,
    settings: Settings | None = None,
    with_research: bool = True,
) -> FastAPI:
    services = (
        ResearchAPIServices(
            store=store,
            executor=_Executor(),  # type: ignore[arg-type]
            serving=ServingIdentity(_SNAPSHOT, "profile-v1"),
            llm_available=llm_available,
        )
        if with_research
        else None
    )
    return create_app(
        settings=settings
        or Settings(
            environment="test",
            database_url="postgresql://test:test@localhost:5432/research_test",
            qdrant_url="http://localhost:26333",
        ),
        dependency_checker=_Readiness(),
        research_services=services,
        auth_settings=AuthSettings(mode="api_key", bind_host="127.0.0.1"),
        api_key_store=api_key_store,
    )


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    key: str,
    body: dict[str, object] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(
            method, path, json=body, headers={"Authorization": f"Bearer {key}"}
        )


async def _keys() -> tuple[InMemoryApiKeyStore, dict[str, str]]:
    store = InMemoryApiKeyStore()
    _, alice = await store.create("alice", (Scope.RESEARCH, Scope.READ))
    _, bob = await store.create("bob", (Scope.RESEARCH, Scope.READ))
    _, ops = await store.create("ops", (Scope.ADMIN,))
    _, research_only = await store.create("researcher", (Scope.RESEARCH,))
    _, reader = await store.create("reader", (Scope.READ,))
    return store, {
        "alice": alice,
        "bob": bob,
        "ops": ops,
        "research_only": research_only,
        "reader": reader,
    }


def _body(question: str = "Synthetic research question") -> dict[str, object]:
    return {"question": question, "mode": "quick"}


def test_list_returns_only_own_runs_newest_first() -> None:
    async def exercise():
        keys_store, keys = await _keys()
        store = InMemoryRunStore()
        app = _app(store, api_key_store=keys_store)
        created = []
        for question in ("Synthetic one", "Synthetic two", "Synthetic three"):
            created.append(
                str(
                    await store.create_run(
                        ResearchRequest(question=question, mode="quick"),
                        principal="alice",
                    )
                )
            )
        await store.create_run(
            ResearchRequest(question="Synthetic bob", mode="quick"),
            principal="bob",
        )
        response = await _request(app, "GET", "/v1/research", key=keys["alice"])
        return response, created

    response, created = asyncio.run(exercise())
    payload = response.json()
    assert response.status_code == 200
    assert [run["run_id"] for run in payload["runs"]] == list(reversed(created))
    assert [run["question"] for run in payload["runs"]] == [
        "Synthetic three",
        "Synthetic two",
        "Synthetic one",
    ]
    assert all(
        run["mode"] == "quick" and run["status"] == "queued" for run in payload["runs"]
    )


def test_list_paginates_with_cursor() -> None:
    async def exercise():
        keys_store, keys = await _keys()
        store = InMemoryRunStore()
        app = _app(store, api_key_store=keys_store)
        for index in range(5):
            await store.create_run(
                ResearchRequest(question=f"Synthetic {index}", mode="quick"),
                principal="alice",
            )
        pages = []
        cursor = None
        for _ in range(3):
            path = "/v1/research?limit=2" + (f"&cursor={cursor}" if cursor else "")
            response = await _request(app, "GET", path, key=keys["alice"])
            pages.append(response.json())
            cursor = pages[-1]["next_cursor"]
        return pages

    pages = asyncio.run(exercise())
    assert [len(page["runs"]) for page in pages] == [2, 2, 1]
    assert pages[-1]["next_cursor"] is None
    ids = [run["run_id"] for page in pages for run in page["runs"]]
    assert len(ids) == len(set(ids)) == 5


def test_list_rejects_bad_cursor_and_limit() -> None:
    async def exercise():
        keys_store, keys = await _keys()
        app = _app(InMemoryRunStore(), api_key_store=keys_store)
        return await asyncio.gather(
            _request(app, "GET", "/v1/research?cursor=zq7731", key=keys["alice"]),
            _request(app, "GET", "/v1/research?limit=0", key=keys["alice"]),
            _request(app, "GET", "/v1/research?limit=51", key=keys["alice"]),
        )

    bad_cursor, zero, too_many = asyncio.run(exercise())
    assert bad_cursor.status_code == 422
    assert bad_cursor.json()["error"]["code"] == "invalid_cursor"
    assert zero.status_code == too_many.status_code == 422


def test_list_reports_outcome_and_failure() -> None:
    async def exercise():
        keys_store, keys = await _keys()
        store = InMemoryRunStore()
        app = _app(store, api_key_store=keys_store)
        completed = await store.create_run(
            ResearchRequest(question="Synthetic completed", mode="quick"),
            principal="alice",
        )
        await store.mark_running(
            completed,
            provenance=RunProvenance(
                snapshot_id=_SNAPSHOT,
                retrieval_profile_id="profile-v1",
                configuration_id=f"sha256:{'b' * 64}",
                code_revision="test",
                model=ModelIdentity(name="fake", runtime="test", context_tokens=4096),
                thinking={CallKind.PLAN: False},
                prompt_versions={"system": "v1"},
                budgets=RunBudgets(),
                trace_id="synthetic-trace",
            ),
        )
        await store.complete_run(
            completed,
            answer="Synthetic answer",
            outcome=AnswerOutcome.ANSWERED,
            claims=(),
            usage=RunUsage(),
        )
        failed = await store.create_run(
            ResearchRequest(question="Synthetic failed", mode="quick"),
            principal="alice",
        )
        await store.fail_run(
            failed,
            category=FailureCategory.TIMEOUT,
            message="synthetic failure",
            usage=RunUsage(),
        )
        response = await _request(app, "GET", "/v1/research", key=keys["alice"])
        return response

    rows = asyncio.run(exercise()).json()["runs"]
    by_status = {row["status"]: row for row in rows}
    assert by_status["completed"]["answer_outcome"] == "answered"
    assert by_status["failed"]["failure_category"] == "timeout"


def test_list_requires_read_scope() -> None:
    async def exercise():
        keys_store, keys = await _keys()
        app = _app(InMemoryRunStore(), api_key_store=keys_store)
        return await _request(app, "GET", "/v1/research", key=keys["research_only"])

    assert asyncio.run(exercise()).status_code == 403


def test_get_run_still_hides_other_principals() -> None:
    async def exercise():
        keys_store, keys = await _keys()
        app = _app(InMemoryRunStore(), api_key_store=keys_store)
        created = await _request(
            app, "POST", "/v1/research", key=keys["alice"], body=_body()
        )
        run_id = created.json()["run_id"]
        bob = await _request(app, "GET", f"/v1/research/{run_id}", key=keys["bob"])
        admin = await _request(app, "GET", f"/v1/research/{run_id}", key=keys["ops"])
        return bob, admin

    bob, admin = asyncio.run(exercise())
    assert bob.status_code == 404
    assert bob.json()["error"]["code"] == "run_not_found"
    assert admin.status_code == 200


def test_cursor_round_trip_and_rejects_naive_datetime() -> None:
    created_at = datetime(2026, 10, 23, 12, 30, tzinfo=UTC)
    run_id = UUID("9eff3f48-9555-48d7-a8b6-0cf2bce694e1")
    assert decode_run_cursor(encode_run_cursor(created_at, run_id)) == (
        created_at,
        run_id,
    )
    payload = json.dumps(
        {"created_at": "2026-10-23T12:30:00", "run_id": str(run_id)},
        separators=(",", ":"),
    ).encode()
    cursor = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    try:
        decode_run_cursor(cursor)
    except AppError as error:
        assert error.code == "invalid_cursor"
    else:
        raise AssertionError("naive datetime cursor was accepted")
