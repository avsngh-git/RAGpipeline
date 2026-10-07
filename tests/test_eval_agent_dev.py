from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from research_platform.config import Settings
from research_platform.evaluation.experiments import (
    ExperimentItemWriter,
    read_items,
)
from research_platform.evaluation.suites import SUITES
from research_platform.evaluation.suites.agent_dev import AgentDevSuite
from research_platform.evaluation.suites.base import SuiteContext
from research_platform.llm.types import ModelIdentity
from research_platform.runs.contracts import (
    AnswerOutcome,
    ResearchRunView,
    RunBudgets,
    RunProvenance,
    RunStatus,
    RunUsage,
    configuration_id,
)
from research_platform.runs.memory import InMemoryRunStore

QUESTION_MARKER = "private-question-marker-zq7731"


def _configuration() -> dict[str, object]:
    return {
        "model": {"name": "synthetic-model", "digest": "digest-1"},
        "prompt_versions": {"plan": "plan-v1"},
        "tool_schema_digest": "tools-1",
        "decoding": {"seed": 7},
    }


CONFIGURATION_ID = configuration_id(_configuration())


def _view(
    *,
    run_id: str,
    question: str,
    mode: str,
    configuration_id: str = CONFIGURATION_ID,
    status: str = "completed",
    answer_outcome: str = "answered",
) -> dict[str, object]:
    provenance = RunProvenance(
        snapshot_id=uuid4(),
        retrieval_profile_id="synthetic-profile",
        configuration_id=configuration_id,
        code_revision="synthetic-revision",
        model=ModelIdentity(
            name="synthetic-model", runtime="synthetic", context_tokens=4096
        ),
        thinking={},
        prompt_versions={},
        budgets=RunBudgets(),
        trace_id="synthetic-trace",
    )
    view = ResearchRunView(
        run_id=run_id,
        status=RunStatus(status),
        mode=mode,
        question=question,
        answer_outcome=AnswerOutcome(answer_outcome) if status == "completed" else None,
        failure_category=None,
        provenance=provenance,
        usage=RunUsage(active_seconds=3.5, tool_calls=2, model_calls=1),
        created_at="2026-10-07T10:00:00Z",
    )
    return view.model_dump(mode="json")


def _task_file(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tasks": [
                    {
                        "task_id": "supported-1",
                        "source": "calibration-v1",
                        "question": QUESTION_MARKER,
                        "filters": {"year_from": 2023},
                        "unsupported": False,
                        "judged_paper_ids": ["W1"],
                    },
                    {
                        "task_id": "unsupported-1",
                        "source": "calibration-v1",
                        "question": "synthetic unsupported question",
                        "filters": None,
                        "unsupported": True,
                        "judged_paper_ids": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _context(tmp_path: Path, task_path: Path, **options: str) -> SuiteContext:
    return SuiteContext(
        experiment_id=uuid4(),
        writer=ExperimentItemWriter(uuid4(), root=tmp_path),
        settings=Settings(environment="test"),
        options={"tasks": str(task_path), **options},
    )


def _transport(
    *,
    config_ids: tuple[str, ...] = (CONFIGURATION_ID,),
    running_polls: int = 0,
    expected_key: str | None = None,
):
    submitted: dict[str, tuple[str, str, int]] = {}
    counts: Counter[str] = Counter()

    def handle(request: httpx.Request) -> httpx.Response:
        if expected_key is not None:
            assert request.headers.get("authorization") == f"Bearer {expected_key}"
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["question"]
            assert payload["mode"] in {"quick", "deep_research"}
            if payload["question"] == QUESTION_MARKER:
                assert payload["filters"] == {"year_from": 2023}
            run_id = str(uuid4())
            submitted[run_id] = (
                payload["question"],
                payload["mode"],
                len(submitted),
            )
            return httpx.Response(202, json={"run_id": run_id})
        run_id = request.url.path.rsplit("/", 1)[-1]
        question, mode, index = submitted[run_id]
        counts[run_id] += 1
        if counts[run_id] <= running_polls:
            return httpx.Response(200, json={"status": "running"})
        return httpx.Response(
            200,
            json=_view(
                run_id=run_id,
                question=question,
                mode=mode,
                configuration_id=config_ids[index % len(config_ids)],
                answer_outcome=(
                    "insufficient_evidence" if "unsupported" in question else "answered"
                ),
            ),
        )

    return httpx.MockTransport(handle), counts


async def _execute(
    suite: AgentDevSuite,
    context: SuiteContext,
):
    return await suite.run(context)


@pytest.mark.anyio
async def test_runs_every_task_and_mode(tmp_path: Path) -> None:
    task_path = _task_file(tmp_path / "tasks.json")
    transport, _ = _transport()
    client = httpx.AsyncClient(transport=transport)
    store = InMemoryRunStore()
    configuration = _configuration()
    config_id = CONFIGURATION_ID
    await store.save_run_configuration(config_id, configuration, provenance_version=2)
    writer = ExperimentItemWriter(uuid4(), root=tmp_path)
    outcome = await AgentDevSuite(client=client, store=store).run(
        SuiteContext(
            uuid4(), writer, Settings(environment="test"), {"tasks": str(task_path)}
        )
    )
    await client.aclose()

    items = read_items(writer.path)
    assert [item["item_id"] for item in items] == [
        "supported-1:quick",
        "unsupported-1:quick",
        "supported-1:deep_research",
        "unsupported-1:deep_research",
    ]
    assert outcome.item_count == 4
    assert outcome.configuration_id == config_id
    assert outcome.configuration == configuration
    assert outcome.versions == {
        "model": "synthetic-model",
        "model_digest": "digest-1",
        "prompt.plan": "plan-v1",
        "tool_schema": "tools-1",
    }
    assert outcome.random_seed == 7
    assert outcome.metrics["runs"] == 4
    assert outcome.metrics["quick.completed"] == 2


@pytest.mark.anyio
async def test_polls_until_terminal(tmp_path: Path) -> None:
    task_path = _task_file(tmp_path / "tasks.json")
    transport, counts = _transport(running_polls=2)
    client = httpx.AsyncClient(transport=transport)
    store = InMemoryRunStore()
    config_id = CONFIGURATION_ID
    await store.save_run_configuration(
        config_id, _configuration(), provenance_version=2
    )
    writer = ExperimentItemWriter(uuid4(), root=tmp_path)
    suite = AgentDevSuite(client=client, store=store, sleep=lambda _: asyncio.sleep(0))
    await suite.run(
        SuiteContext(
            uuid4(),
            writer,
            Settings(environment="test"),
            {"tasks": str(task_path)},
        )
    )
    await client.aclose()

    assert counts
    assert set(counts.values()) == {3}


@pytest.mark.anyio
async def test_sends_api_key_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_path = _task_file(tmp_path / "tasks.json")
    monkeypatch.setenv("RESEARCH_PLATFORM_API_KEY", "synthetic-api-key")
    transport, _ = _transport(expected_key="synthetic-api-key")
    client = httpx.AsyncClient(transport=transport)
    store = InMemoryRunStore()
    config_id = CONFIGURATION_ID
    await store.save_run_configuration(
        config_id, _configuration(), provenance_version=2
    )
    await AgentDevSuite(
        client=client, store=store, sleep=lambda _: asyncio.sleep(0)
    ).run(_context(tmp_path, task_path))
    await client.aclose()


@pytest.mark.anyio
async def test_resume_skips_existing_pairs(tmp_path: Path) -> None:
    task_path = _task_file(tmp_path / "tasks.json")
    resumed = tmp_path / "prior-items.jsonl"
    resumed.write_text(
        json.dumps(
            {
                "item_id": "supported-1:quick",
                "task_id": "supported-1",
                "mode": "quick",
                "unsupported": False,
                "run_id": str(uuid4()),
                "status": "completed",
                "answer_outcome": "answered",
                "failure_category": None,
                "active_seconds": 1.0,
                "tool_calls": 1,
                "model_calls": 1,
                "kept_claims": 1,
                "rejected_claims": 0,
                "unsupported_claims": 0,
                "configuration_id": CONFIGURATION_ID,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    transport, _ = _transport()
    client = httpx.AsyncClient(transport=transport)
    store = InMemoryRunStore()
    config_id = CONFIGURATION_ID
    await store.save_run_configuration(
        config_id, _configuration(), provenance_version=2
    )
    writer = ExperimentItemWriter(uuid4(), root=tmp_path)
    await AgentDevSuite(client=client, store=store).run(
        SuiteContext(
            uuid4(),
            writer,
            Settings(environment="test"),
            {"tasks": str(task_path), "resume_items": str(resumed)},
        )
    )
    await client.aclose()

    items = read_items(writer.path)
    assert len(items) == 4
    assert sum(item["item_id"] == "supported-1:quick" for item in items) == 1


@pytest.mark.anyio
async def test_mixed_configuration_reported(tmp_path: Path) -> None:
    task_path = _task_file(tmp_path / "tasks.json")
    config_ids = (
        CONFIGURATION_ID,
        configuration_id({"model": {"name": "other"}}),
    )
    transport, _ = _transport(config_ids=config_ids)
    client = httpx.AsyncClient(transport=transport)
    suite = AgentDevSuite(client=client, store=InMemoryRunStore())
    outcome = await suite.run(_context(tmp_path, task_path))
    await client.aclose()

    assert outcome.configuration_id is None
    assert outcome.configuration == {}
    assert outcome.failures == {"mixed_configuration": 2}


@pytest.mark.anyio
async def test_items_have_no_question_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task_path = _task_file(tmp_path / "tasks.json")
    transport, _ = _transport()
    client = httpx.AsyncClient(transport=transport)
    store = InMemoryRunStore()
    config_id = CONFIGURATION_ID
    await store.save_run_configuration(
        config_id, _configuration(), provenance_version=2
    )
    writer = ExperimentItemWriter(uuid4(), root=tmp_path)
    await AgentDevSuite(client=client, store=store).run(
        SuiteContext(
            uuid4(),
            writer,
            Settings(environment="test"),
            {"tasks": str(task_path)},
        )
    )
    await client.aclose()

    captured = capsys.readouterr()
    assert QUESTION_MARKER not in writer.path.read_text(encoding="utf-8")
    assert QUESTION_MARKER not in captured.out
    assert all("question" not in item for item in read_items(writer.path))


@pytest.mark.anyio
async def test_poll_timeout_item(tmp_path: Path) -> None:
    task_path = _task_file(tmp_path / "tasks.json")
    transport, counts = _transport(running_polls=100)
    client = httpx.AsyncClient(transport=transport)
    writer = ExperimentItemWriter(uuid4(), root=tmp_path)

    async def slow_sleep(_: float) -> None:
        await asyncio.sleep(0.02)

    outcome = await AgentDevSuite(
        client=client,
        store=InMemoryRunStore(),
        sleep=slow_sleep,
    ).run(
        SuiteContext(
            uuid4(),
            writer,
            Settings(environment="test"),
            {"tasks": str(task_path), "run_timeout_seconds": "0.01"},
        )
    )
    await client.aclose()

    items = read_items(writer.path)
    assert items[0]["status"] == "poll_timeout"
    assert outcome.failures["poll_timeout"] == 4
    assert counts


def test_agent_dev_suite_is_registered() -> None:
    assert isinstance(SUITES["agent-dev"], AgentDevSuite)
