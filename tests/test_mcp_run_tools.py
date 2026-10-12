"""Protocol tests for MCP research-run tools and resources."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import anyio.to_thread
import pytest
from mcp import Client, MCPError

from research_platform.auth.keys import Principal, Scope
from research_platform.mcp.server import build_mcp_server
from research_platform.mcp.testing import fake_state, make_settings
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimResult,
    EvidenceCitation,
    ResearchMode,
    ResearchRequest,
    ResearchRunView,
    RunStatus,
    RunUsage,
    SupportLabel,
)
from research_platform.runs.memory import InMemoryRunStore


@contextmanager
def _authenticated(principal: Principal) -> Iterator[None]:
    from research_platform.mcp.principal import principal_context

    with principal_context(principal):
        yield


class CompletedRunStore(InMemoryRunStore):
    async def get_run_view(self, run_id: UUID) -> ResearchRunView:
        stored = await self.get_run(run_id)
        return ResearchRunView(
            run_id=run_id,
            status=RunStatus.COMPLETED,
            mode=ResearchMode.QUICK,
            question="A synthetic research question",
            answer="A synthetic claim [E1].",
            answer_outcome=AnswerOutcome.ANSWERED,
            claims=(
                ClaimResult(
                    claim_id="claim-1",
                    text="A synthetic claim.",
                    quote="zq7731",
                    evidence=(
                        EvidenceCitation(
                            handle="E1", chunk_id="chunk-1", paper_id="W123"
                        ),
                    ),
                    support=SupportLabel.SUPPORTED,
                ),
            ),
            usage=RunUsage(),
            created_at=stored.created_at,
        )


def _as_client(
    state: Any,
    principal: Principal,
    action: Callable[[Client], Awaitable[Any]],
) -> Any:
    async def run() -> Any:
        with _authenticated(principal):
            async with Client(build_mcp_server(state)) as client:
                return await action(client)

    return asyncio.run(run())


def _research_principal(name: str = "alice") -> Principal:
    return Principal(name, frozenset({Scope.READ, Scope.RESEARCH}))


def test_start_research_run_queues_a_run() -> None:
    state = fake_state()
    result = _as_client(
        state,
        _research_principal(),
        lambda client: client.call_tool(
            "start_research_run", {"question": "What supports hybrid retrieval?"}
        ),
    )

    assert not result.is_error
    run = result.structured_content["run"]
    assert run["status"] == "queued"
    assert result.structured_content["poll_after_seconds"] == 30
    run_id = UUID(run["run_id"])
    assert state.research_services.executor.submissions == [run_id]
    stored = asyncio.run(state.research_services.store.get_run(run_id))
    assert stored.principal == "alice"


def test_start_requires_the_research_scope() -> None:
    result = _as_client(
        fake_state(),
        Principal("reader", frozenset({Scope.READ})),
        lambda client: client.call_tool(
            "start_research_run", {"question": "What supports hybrid retrieval?"}
        ),
    )

    assert result.is_error
    assert "insufficient_scope" in result.content[0].text


def test_ingestion_permission_follows_the_ingest_scope() -> None:
    states = (
        (fake_state(), _research_principal("reader"), False),
        (
            fake_state(),
            Principal(
                "ingester", frozenset({Scope.READ, Scope.RESEARCH, Scope.INGEST})
            ),
            True,
        ),
    )
    for state, principal, expected in states:
        result = _as_client(
            state,
            principal,
            lambda client: client.call_tool(
                "start_research_run",
                {"question": "What supports hybrid retrieval?"},
            ),
        )
        run_id = UUID(result.structured_content["run"]["run_id"])
        stored = asyncio.run(state.research_services.store.get_run(run_id))
        assert stored.ingestion_permitted is expected


def test_deep_research_mode_is_accepted() -> None:
    result = _as_client(
        fake_state(),
        _research_principal(),
        lambda client: client.call_tool(
            "start_research_run",
            {"question": "What supports hybrid retrieval?", "mode": "deep_research"},
        ),
    )

    assert not result.is_error
    assert result.structured_content["run"]["mode"] == "deep_research"


def test_short_question_is_rejected() -> None:
    result = _as_client(
        fake_state(),
        _research_principal(),
        lambda client: client.call_tool("start_research_run", {"question": "ab"}),
    )

    assert result.is_error


def test_get_research_run_returns_the_view() -> None:
    state = fake_state()

    async def start_and_read(client: Client) -> Any:
        started = await client.call_tool(
            "start_research_run", {"question": "What supports hybrid retrieval?"}
        )
        run_id = started.structured_content["run"]["run_id"]
        return await client.call_tool("get_research_run", {"run_id": run_id})

    result = _as_client(state, _research_principal(), start_and_read)

    assert not result.is_error
    assert result.structured_content["run"]["run_id"]
    assert result.structured_content["run"]["status"] == "queued"


def test_other_principals_runs_are_not_found() -> None:
    state = fake_state()

    async def start_and_read_as_other(client: Client) -> Any:
        started = await client.call_tool(
            "start_research_run", {"question": "What supports hybrid retrieval?"}
        )
        run_id = started.structured_content["run"]["run_id"]
        with _authenticated(_research_principal("bob")):
            return await client.call_tool("get_research_run", {"run_id": run_id})

    result = _as_client(state, _research_principal(), start_and_read_as_other)

    assert result.is_error
    assert "run_not_found" in result.content[0].text


def _completed_run_result(*, text_policy: str) -> Any:
    store = CompletedRunStore()
    state = fake_state(
        store=store,
        settings=make_settings(text_policy=text_policy),
    )

    async def create_and_read(client: Client) -> Any:
        request = ResearchRequest(
            question="A synthetic research question", mode=ResearchMode.QUICK
        )
        run_id = await store.create_run(request, principal="alice")
        return await client.call_tool("get_research_run", {"run_id": str(run_id)})

    return _as_client(state, _research_principal(), create_and_read)


def test_completed_run_has_no_poll_hint_and_no_quotes() -> None:
    result = _completed_run_result(text_policy="public_display_only")

    assert result.structured_content["poll_after_seconds"] is None
    assert "zq7731" not in json.dumps(result.structured_content)
    assert "Claim quotes are withheld" in result.structured_content["note"]


def test_quotes_are_kept_for_a_trusted_private_client() -> None:
    result = _completed_run_result(text_policy="trusted_private_client")

    assert "zq7731" in json.dumps(result.structured_content)
    assert "Claim quotes are withheld" not in result.structured_content["note"]


def test_run_resource_reads_json(monkeypatch: pytest.MonkeyPatch) -> None:
    state = fake_state()

    async def run_sync_inline(
        func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(anyio.to_thread, "run_sync", run_sync_inline)

    async def start_and_read(client: Client) -> Any:
        started = await client.call_tool(
            "start_research_run", {"question": "What supports hybrid retrieval?"}
        )
        run_id = started.structured_content["run"]["run_id"]
        return await client.read_resource(f"research-run://{run_id}")

    resource = _as_client(state, _research_principal(), start_and_read)

    payload = json.loads(resource.contents[0].text)
    assert payload["run"]["run_id"]


def test_run_resource_rejects_a_bad_id() -> None:
    async def read(client: Client) -> Any:
        with pytest.raises(MCPError, match="invalid_request"):
            await client.read_resource("research-run://not-a-uuid")
        return None

    _as_client(fake_state(), _research_principal(), read)


def test_start_is_not_marked_read_only() -> None:
    async def list_tools(client: Client) -> Any:
        return await client.list_tools()

    result = _as_client(fake_state(), _research_principal(), list_tools)
    annotations = {tool.name: tool.annotations for tool in result.tools}

    assert annotations["start_research_run"].read_only_hint is False
    assert annotations["get_research_run"].read_only_hint is True
