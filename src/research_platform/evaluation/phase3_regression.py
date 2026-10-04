"""Data-driven synthetic regression cases for complete Phase 3 research runs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph

from research_platform.agents.graph_deep import build_deep_graph
from research_platform.agents.graph_quick import build_quick_graph
from research_platform.agents.nodes import NodeDependencies
from research_platform.agents.state import ResearchState
from research_platform.llm.contracts import (
    LLMError,
    LLMInvalidOutput,
    LLMRequestRejected,
    LLMTimeout,
    LLMUnavailable,
)
from research_platform.llm.scripted import ScriptedLLM, ScriptedReply
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.runs.contracts import (
    ResearchMode,
    ResearchRequest,
    ResearchRunView,
    RunBudgets,
    RunStatus,
)
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.repository import EvidenceRecord, ToolCallRecord
from research_platform.runs.runner import (
    GraphBuilder,
    ResearchRunner,
    RunnerDependencies,
    ServingIdentity,
    build_provenance,
)
from research_platform.tools.fakes import (
    FakeCorpus,
    FakePaper,
    FakePassage,
    fake_services,
)
from research_platform.tools.research_tools import ResearchTools

_IDENTITY = ModelIdentity(name="scripted", runtime="scripted", context_tokens=8192)
_SNAPSHOT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_PROFILE = "sha256:" + "a" * 64
_CODE_REVISION = "synthetic-phase3-regression-v1"
_ERRORS = {
    "LLMUnavailable": LLMUnavailable,
    "LLMTimeout": LLMTimeout,
    "LLMRequestRejected": LLMRequestRejected,
}
_CASE_KEYS = frozenset(
    {
        "case_id",
        "category",
        "request",
        "budgets",
        "replies",
        "interrupt_after_node",
        "fault_injection",
        "initial_active_seconds",
        "expect",
    }
)
_EXPECT_KEYS = frozenset(
    {
        "status",
        "answer_outcome",
        "failure_category",
        "tools",
        "tool_ordinals",
        "tool_statuses",
        "claims",
        "rejected_claims",
        "unsupported_claims",
        "answer_excludes",
        "evaluate_prompt_contains",
        "claim_handles",
        "evidence_handles",
        "tool_calls",
        "plan_rounds",
        "model_calls",
        "resumes",
        "tool_calls_at_most",
        "plan_rounds_at_most",
    }
)
_TOOL_STATUSES = frozenset({"succeeded", "failed", "rejected", "cached"})
_NODE_NAMES = frozenset({"execute", "answer"})
_FAULTS = frozenset({"recursion_guard_loop"})


@dataclass(frozen=True)
class RegressionCase:
    """One validated scripted whole-run scenario."""

    case_id: str
    category: str
    request: ResearchRequest
    budgets: RunBudgets
    replies: tuple[ScriptedReply, ...]
    interrupt_after_node: str | None
    fault_injection: str | None
    initial_active_seconds: float | None
    expect: Mapping[str, object]


@dataclass(frozen=True)
class RegressionResult:
    """Observed outcome and safe, data-free mismatch descriptions."""

    case_id: str
    category: str
    passed: bool
    mismatches: tuple[str, ...]


class _RecordingRunStore(InMemoryRunStore):
    """Keep the store's idempotent tool persistence visible to the harness."""

    def __init__(self) -> None:
        super().__init__()
        self._persisted_calls: dict[UUID, dict[int, ToolCallRecord]] = {}

    async def append_tool_call(self, run_id: UUID, record: ToolCallRecord) -> None:
        await super().append_tool_call(run_id, record)
        self._persisted_calls.setdefault(run_id, {}).setdefault(record.ordinal, record)

    def tool_calls(self, run_id: UUID) -> tuple[ToolCallRecord, ...]:
        records = self._persisted_calls.get(run_id, {})
        return tuple(records[index] for index in sorted(records))


class _CancelAtCheckpointSaver(InMemorySaver):
    """Cancel the outer runner immediately after a named node checkpoint."""

    def __init__(self, node_name: str) -> None:
        super().__init__()
        self.node_name = node_name
        self.target_step = {"execute": 2, "answer": 4}[node_name]
        self.runner_task: asyncio.Task[RunStatus] | None = None
        self.interrupted = False

    async def aput(self, config, checkpoint, metadata, new_versions):  # type: ignore[no-untyped-def]
        result = await super().aput(config, checkpoint, metadata, new_versions)
        if (
            not self.interrupted
            and metadata.get("source") == "loop"
            and metadata.get("step") == self.target_step
        ):
            if self.node_name not in checkpoint.get("versions_seen", {}):
                raise AssertionError(
                    "target checkpoint does not record the requested node as complete"
                )
            if self.runner_task is None:
                raise RuntimeError("runner task was not attached before checkpoint")
            self.interrupted = True
            self.runner_task.cancel()
        return result


def load_cases(path: Path) -> tuple[RegressionCase, ...]:
    """Load versioned synthetic cases and reject unsupported test directives.

    Schema version 2 scripts quoted claims checked in code (ADR-0025). Version 1
    scripted a support judge and is kept only as the Phase 3 acceptance record.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise ValueError("regression case file must use schema_version 2")
    if set(payload) != {"schema_version", "corpus", "cases"}:
        raise ValueError("regression case file has unexpected top-level fields")
    corpus_data = payload.get("corpus")
    if not isinstance(corpus_data, dict) or set(corpus_data) != {
        "snapshot_id",
        "papers",
        "passages",
        "citations",
        "failing_queries",
    }:
        raise ValueError("corpus must declare only the synthetic corpus fields")
    cases_data = payload.get("cases")
    if not isinstance(cases_data, list):
        raise ValueError("cases must be an array")

    corpus = _load_corpus(corpus_data)
    cases = tuple(_load_case(item) for item in cases_data)
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case_id values must be unique")
    _validate_directives(cases, corpus)
    return cases


def load_corpus(path: Path) -> FakeCorpus:
    """Load the shared synthetic corpus from a versioned case file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise ValueError("regression case file must use schema_version 2")
    corpus_data = payload.get("corpus")
    if not isinstance(corpus_data, dict):
        raise ValueError("regression case file must include a corpus object")
    return _load_corpus(corpus_data)


async def run_case(case: RegressionCase, corpus: FakeCorpus) -> RegressionResult:
    """Run one case through the production graphs, tools, and runner."""
    store = _RecordingRunStore()
    search, papers, citations, related = fake_services(corpus)
    tools = ResearchTools(
        search=search,
        papers=papers,
        citations=citations,
        related=related,
    )
    llm = ScriptedLLM(case.replies, identity=_IDENTITY)
    saver: InMemorySaver = (
        _CancelAtCheckpointSaver(case.interrupt_after_node)
        if case.interrupt_after_node is not None
        else InMemorySaver()
    )
    graphs: dict[ResearchMode, GraphBuilder] = {
        ResearchMode.QUICK: build_quick_graph,
        ResearchMode.DEEP_RESEARCH: build_deep_graph,
    }
    if case.fault_injection == "recursion_guard_loop":
        graphs[case.request.mode] = _build_recursion_guard_graph

    runner = ResearchRunner(
        RunnerDependencies(
            repository=store,
            tools=tools,
            llm=llm,
            checkpointer=saver,
            serving=ServingIdentity(_SNAPSHOT, _PROFILE),
            thinking=frozenset({CallKind.PLAN}),
            code_revision=_CODE_REVISION,
            graphs=graphs,
            budgets=case.budgets,
        )
    )
    run_id = await store.create_run(case.request)
    mismatches: list[str] = []

    if case.initial_active_seconds is not None:
        provenance = build_provenance(
            run_id=run_id,
            request=case.request,
            serving=ServingIdentity(_SNAPSHOT, _PROFILE),
            model=_IDENTITY,
            thinking=frozenset({CallKind.PLAN}),
            budgets=case.budgets,
            code_revision=_CODE_REVISION,
        )
        await store.mark_running(run_id, provenance=provenance)
        await store.add_active_seconds(run_id, case.initial_active_seconds)

    if isinstance(saver, _CancelAtCheckpointSaver):
        task = asyncio.create_task(runner.run(run_id))
        saver.runner_task = task
        try:
            await task
            mismatches.append(
                "runner completed without the requested checkpoint cancellation"
            )
        except asyncio.CancelledError:
            if not saver.interrupted:
                mismatches.append(
                    "runner was cancelled before the requested checkpoint"
                )
        if saver.interrupted:
            await runner.run(run_id)
    else:
        await runner.run(run_id)

    view = await store.get_run_view(run_id)
    tool_calls = store.tool_calls(run_id)
    evidence = await store.load_evidence(run_id)
    mismatches.extend(_compare(case.expect, view, tool_calls, evidence, llm))
    if llm.remaining != 0:
        mismatches.append(f"scripted LLM has {llm.remaining} unconsumed replies")
    return RegressionResult(
        case_id=case.case_id,
        category=case.category,
        passed=not mismatches,
        mismatches=tuple(mismatches),
    )


def _load_corpus(data: Mapping[str, object]) -> FakeCorpus:
    papers_raw = data.get("papers")
    passages_raw = data.get("passages")
    citations_raw = data.get("citations")
    failing_raw = data.get("failing_queries")
    if not isinstance(papers_raw, list) or not isinstance(passages_raw, list):
        raise ValueError("corpus papers and passages must be arrays")
    if not isinstance(citations_raw, list) or not isinstance(failing_raw, list):
        raise ValueError("corpus citations and failing_queries must be arrays")
    papers = tuple(
        FakePaper(
            paper_id=_required_string(item, "paper_id"),
            title=_required_string(item, "title"),
            publication_year=_required_int(item, "publication_year"),
        )
        for item in _mapping_items(papers_raw, "papers")
    )
    passages = tuple(
        FakePassage(
            chunk_id=_required_string(item, "chunk_id"),
            paper_id=_required_string(item, "paper_id"),
            text=_required_string(item, "text"),
            kind=_optional_string(item, "kind", "text"),
        )
        for item in _mapping_items(passages_raw, "passages")
    )
    citations: list[tuple[str, str]] = []
    for edge in citations_raw:
        if (
            not isinstance(edge, list)
            or len(edge) != 2
            or not all(isinstance(value, str) for value in edge)
        ):
            raise ValueError("each citation edge must be a pair of paper IDs")
        citations.append((edge[0], edge[1]))
    if not all(isinstance(value, str) for value in failing_raw):
        raise ValueError("failing_queries must contain only strings")
    return FakeCorpus(
        snapshot_id=UUID(_required_string(data, "snapshot_id")),
        papers=papers,
        passages=passages,
        citations=tuple(citations),
        failing_queries=frozenset(failing_raw),
    )


def _load_case(value: object) -> RegressionCase:
    if not isinstance(value, dict) or set(value) - _CASE_KEYS:
        raise ValueError("case has unexpected fields")
    case_id = _required_string(value, "case_id")
    category = _required_string(value, "category")
    try:
        request = ResearchRequest.model_validate(value.get("request"))
        budgets = RunBudgets.model_validate(value.get("budgets", {}))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"case {case_id} has invalid request or budgets") from exc
    replies_raw = value.get("replies")
    if not isinstance(replies_raw, list):
        raise ValueError(f"case {case_id} replies must be an array")
    replies = tuple(_load_reply(case_id, item) for item in replies_raw)
    interrupt = value.get("interrupt_after_node")
    if interrupt is not None and interrupt not in _NODE_NAMES:
        raise ValueError(f"case {case_id} has unsupported interrupt node")
    fault = value.get("fault_injection")
    if fault is not None and fault not in _FAULTS:
        raise ValueError(f"case {case_id} has unsupported fault injection")
    active_seconds = value.get("initial_active_seconds")
    if active_seconds is not None and (
        isinstance(active_seconds, bool)
        or not isinstance(active_seconds, (int, float))
        or active_seconds < 0
    ):
        raise ValueError(f"case {case_id} initial_active_seconds must be non-negative")
    expect = value.get("expect")
    if not isinstance(expect, dict) or set(expect) - _EXPECT_KEYS:
        raise ValueError(f"case {case_id} expect has unsupported fields")
    statuses = expect.get("tool_statuses")
    if isinstance(statuses, dict) and any(
        key not in _TOOL_STATUSES for key in statuses
    ):
        raise ValueError(f"case {case_id} has an unsupported tool status")
    for field_name in (
        "tools",
        "tool_ordinals",
        "answer_excludes",
        "evaluate_prompt_contains",
        "evidence_handles",
    ):
        field_value = expect.get(field_name)
        if field_value is not None and (
            not isinstance(field_value, list)
            or not all(
                isinstance(item, str)
                if field_name != "tool_ordinals"
                else isinstance(item, int) and not isinstance(item, bool)
                for item in field_value
            )
        ):
            raise ValueError(f"case {case_id} {field_name} has invalid array values")
    return RegressionCase(
        case_id=case_id,
        category=category,
        request=request,
        budgets=budgets,
        replies=replies,
        interrupt_after_node=cast(str | None, interrupt),
        fault_injection=cast(str | None, fault),
        initial_active_seconds=(
            float(active_seconds) if active_seconds is not None else None
        ),
        expect=expect,
    )


def _load_reply(case_id: str, value: object) -> ScriptedReply:
    if not isinstance(value, dict) or set(value) - {
        "kind",
        "content",
        "tool_calls",
        "error",
    }:
        raise ValueError(f"case {case_id} has an invalid scripted reply")
    try:
        kind = CallKind(_required_string(value, "kind"))
    except ValueError as exc:
        raise ValueError(f"case {case_id} has an unsupported reply kind") from exc
    fields = [name for name in ("content", "tool_calls", "error") if name in value]
    if len(fields) != 1:
        raise ValueError(f"case {case_id} reply must declare exactly one payload")
    if "content" in value:
        if not isinstance(value["content"], str):
            raise ValueError(f"case {case_id} reply content must be a string")
        return ScriptedReply(kind=kind, content=value["content"])
    if "tool_calls" in value:
        calls = value["tool_calls"]
        if not isinstance(calls, list) or not all(
            isinstance(call, dict) for call in calls
        ):
            raise ValueError(f"case {case_id} tool_calls must be an array of objects")
        return ScriptedReply(
            kind=kind,
            tool_calls=tuple(cast(dict[str, object], call) for call in calls),
        )
    error_name = value["error"]
    if not isinstance(error_name, str):
        raise ValueError(f"case {case_id} error must name a scripted LLM error")
    if error_name == "LLMInvalidOutput":
        error: LLMError = LLMInvalidOutput(
            "scripted invalid output", attempts=1, content_preview="synthetic"
        )
    elif error_name in _ERRORS:
        error = _ERRORS[error_name]("scripted failure")
    else:
        raise ValueError(f"case {case_id} names an unsupported scripted error")
    return ScriptedReply(kind=kind, error=error)


def _validate_directives(cases: tuple[RegressionCase, ...], corpus: FakeCorpus) -> None:
    for case in cases:
        if case.interrupt_after_node is not None and case.fault_injection is not None:
            raise ValueError(
                "a case cannot combine interruption and graph fault injection"
            )
        if case.initial_active_seconds is not None and (
            case.initial_active_seconds < case.budgets.max_active_seconds
        ):
            raise ValueError(
                "initial_active_seconds must exhaust the configured budget"
            )
        expected_failure = case.expect.get("failure_category")
        if case.category == "budget" and expected_failure == "budget_exhausted":
            if case.fault_injection != "recursion_guard_loop":
                raise ValueError("recursion budget case requires guard fault injection")
        elif case.fault_injection is not None:
            raise ValueError(
                "graph fault injection is reserved for the recursion guard case"
            )
        if case.category == "budget" and expected_failure == "timeout":
            if case.initial_active_seconds is None:
                raise ValueError("timeout budget case must exhaust prior active time")
        if case.interrupt_after_node is not None and (
            case.category != "resume"
            or case.request.mode is not ResearchMode.DEEP_RESEARCH
        ):
            raise ValueError(
                "node interruption is reserved for deep-research resume cases"
            )
        if expected_failure == "retrieval_error":
            if (
                case.request.mode is not ResearchMode.QUICK
                or case.request.question.lower() not in corpus.failing_queries
            ):
                raise ValueError(
                    "retrieval error case needs a failing quick-search query"
                )


def _compare(
    expected: Mapping[str, object],
    view: ResearchRunView,
    calls: tuple[ToolCallRecord, ...],
    evidence: Mapping[str, EvidenceRecord],
    llm: ScriptedLLM,
) -> list[str]:
    mismatches: list[str] = []
    scalar_fields = {
        "status": view.status.value,
        "answer_outcome": view.answer_outcome.value if view.answer_outcome else None,
        "failure_category": view.failure_category.value
        if view.failure_category
        else None,
        "claims": len(view.claims),
        "rejected_claims": view.usage.rejected_claims,
        "unsupported_claims": view.usage.unsupported_claims,
        "tool_calls": view.usage.tool_calls,
        "plan_rounds": view.usage.plan_rounds,
        "model_calls": view.usage.model_calls,
        "resumes": view.usage.resumes,
    }
    for name, actual in scalar_fields.items():
        if name in expected and expected[name] != actual:
            mismatches.append(f"{name} did not match (actual {actual!r})")
    tool_names = [record.tool_name for record in calls]
    if "tools" in expected and expected["tools"] != tool_names:
        mismatches.append(f"persisted tool order did not match (actual {tool_names!r})")
    if "tool_ordinals" in expected and expected["tool_ordinals"] != [
        record.ordinal for record in calls
    ]:
        mismatches.append("persisted tool ordinals did not match")
    if "tool_statuses" in expected:
        actual_statuses = {
            status: sum(record.status == status for record in calls)
            for status in _TOOL_STATUSES
        }
        statuses = cast(Mapping[str, object], expected["tool_statuses"])
        if any(
            actual_statuses.get(name, 0) != value for name, value in statuses.items()
        ):
            mismatches.append(
                f"persisted tool statuses did not match (actual {dict(actual_statuses)!r})"
            )
    if "claim_handles" in expected:
        actual_handles = [
            [citation.handle for citation in claim.evidence] for claim in view.claims
        ]
        if expected["claim_handles"] != actual_handles:
            mismatches.append("verified claim handles did not match")
    if "evidence_handles" in expected and expected["evidence_handles"] != sorted(
        evidence
    ):
        mismatches.append(
            f"persisted evidence handles did not match (actual {sorted(evidence)!r})"
        )
    if "answer_excludes" in expected:
        answer = view.answer or ""
        if any(
            needle in answer for needle in cast(list[str], expected["answer_excludes"])
        ):
            mismatches.append("answer contains a forbidden substring")
    if "evaluate_prompt_contains" in expected:
        prompts = "\n".join(
            message.content
            for call in llm.calls
            if call.kind is CallKind.EVALUATE
            for message in call.messages
        )
        if any(
            needle not in prompts
            for needle in cast(list[str], expected["evaluate_prompt_contains"])
        ):
            mismatches.append("evaluate prompt omitted expected synthetic context")
    if "tool_calls_at_most" in expected and view.usage.tool_calls > cast(
        int, expected["tool_calls_at_most"]
    ):
        mismatches.append("tool-call budget exceeded")
    if "plan_rounds_at_most" in expected and view.usage.plan_rounds > cast(
        int, expected["plan_rounds_at_most"]
    ):
        mismatches.append("plan-round budget exceeded")
    expected_failure = expected.get("failure_category")
    if view.status is RunStatus.FAILED and view.failure_category is None:
        mismatches.append("failed run has no failure category")
    elif (
        view.status is RunStatus.FAILED
        and view.failure_category is not None
        and expected_failure != view.failure_category.value
        and view.error_message is not None
    ):
        mismatches.append(f"run failed with {view.error_message}")
    return mismatches


def _build_recursion_guard_graph(
    _: NodeDependencies,
) -> StateGraph[ResearchState, None, ResearchState, ResearchState]:
    """Inject a self-loop only to verify the runner's fixed recursion guard."""

    async def repeat(state: ResearchState) -> dict[str, object]:
        return {"observations": state["observations"]}

    builder = StateGraph(ResearchState)
    builder.add_node("recursion_guard_probe", repeat)
    builder.add_edge(START, "recursion_guard_probe")
    builder.add_edge("recursion_guard_probe", "recursion_guard_probe")
    return builder


def _mapping_items(
    values: list[object], field_name: str
) -> tuple[Mapping[str, object], ...]:
    if not all(isinstance(value, dict) for value in values):
        raise ValueError(f"corpus {field_name} entries must be objects")
    return tuple(cast(dict[str, object], value) for value in values)


def _required_string(data: Mapping[str, object], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _required_int(data: Mapping[str, object], name: str) -> int:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _optional_string(data: Mapping[str, object], name: str, default: str) -> str:
    value = data.get(name, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value
