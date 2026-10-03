"""Measure the Phase 3 local generator on synthetic structured-output cases."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping, Sequence, cast

import httpx
from pydantic import BaseModel, Field, ValidationError

from research_platform.agents.actions import (
    ActionBatch,
    SufficiencyDecision,
)
from research_platform.agents.tool_schemas import (
    TOOL_DESCRIPTIONS,
    actions_from_tool_calls,
    research_tool_definitions,
)
from research_platform.config import Settings
from research_platform.llm.contracts import (
    ChatMessage,
    LLMClient,
    LLMError,
    StructuredCall,
)
from research_platform.llm.ollama import OllamaClient
from research_platform.llm.types import CallKind, ModelIdentity
from research_platform.search.application import Phase2Runtime, create_phase2_runtime

logger = logging.getLogger("research_platform.phase3_fitness")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = (
    REPOSITORY_ROOT / "benchmarks/phase3/generator-fitness-cases-v1.json"
)
GPU_MODEL_LAYER_LIMIT = 99
ACTION_TOOL_NAMES = tuple(TOOL_DESCRIPTIONS)
HARNESS_VERSION = 4
OUTPUT_TOKEN_LIMITS = {
    CallKind.PLAN: 384,
    CallKind.EVALUATE: 192,
    CallKind.SYNTHESIZE: 768,
    CallKind.JUDGE: 192,
}
# Ollama counts thinking tokens against num_predict, so thinking calls get extra room
# for reasoning before the answer instead of being truncated inside the thinking.
THINKING_TOKEN_ALLOWANCE = 2048
MAX_PLAN_ACTIONS = 4


def output_token_limit(kind: CallKind, *, think: bool) -> int:
    """Return num_predict for one call, adding the thinking allowance when on."""
    return OUTPUT_TOKEN_LIMITS[kind] + (THINKING_TOKEN_ALLOWANCE if think else 0)


def case_messages(case: FitnessCase) -> tuple[dict[str, str], ...]:
    """Return the case messages, with the tool list appended to plan system prompts."""
    if case.kind is not CallKind.PLAN:
        return case.messages
    tool_lines = "\n".join(
        f"{name}: {TOOL_DESCRIPTIONS[name]}" for name in ACTION_TOOL_NAMES
    )
    guide = (
        f"\n\nTools:\n{tool_lines}\n"
        f"Propose between 1 and {MAX_PLAN_ACTIONS} tool calls that together gather "
        "the evidence needed."
    )
    messages = list(case.messages)
    for index, message in enumerate(messages):
        if message["role"] == "system":
            messages[index] = {**message, "content": message["content"] + guide}
            return tuple(messages)
    return ({"role": "system", "content": guide.strip()}, *messages)


EvidenceHandle = Annotated[str, Field(pattern=r"^E[1-9][0-9]*$")]


class FitnessClaim(BaseModel):
    """One synthetic answer claim and its model-cited evidence handles.

    The handle pattern is part of the JSON schema, so constrained decoding can only
    emit handles such as E3, as P3-11 requires.
    """

    text: str
    handles: list[EvidenceHandle]


class FitnessAnswer(BaseModel):
    """Constrained output used to check answer structure and handle selection."""

    answer: str
    claims: list[FitnessClaim]


class FitnessJudgement(BaseModel):
    """Constrained support labels for the synthetic judging cases."""

    labels: list[Literal["supported", "partial", "unsupported"]]


@dataclass(frozen=True)
class FitnessCase:
    """One prompt and its expected routing or answer properties."""

    case_id: str
    kind: CallKind
    messages: tuple[dict[str, str], ...]
    expect: dict[str, Any]


@dataclass(frozen=True)
class FitnessRecord:
    """Sanitized metrics for one model request; prompt and response text are omitted."""

    case_id: str
    kind: str
    think: bool
    format: str
    repetition: int
    valid: bool
    score: float
    latency_ms: float
    prompt_tokens: int | None
    output_tokens: int | None
    error_type: str | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "kind": self.kind,
            "think": self.think,
            "format": self.format,
            "repetition": self.repetition,
            "valid": self.valid,
            "score": self.score,
            "latency_ms": round(self.latency_ms, 3),
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "error_type": self.error_type,
        }


def load_cases(path: Path = DEFAULT_CASES_PATH) -> tuple[FitnessCase, ...]:
    """Load and validate the versioned synthetic fitness set."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("fitness cases must use schema_version 1")
    cases_value = raw.get("cases")
    if not isinstance(cases_value, list):
        raise ValueError("fitness cases must contain a cases list")

    cases: list[FitnessCase] = []
    for value in cases_value:
        if not isinstance(value, dict):
            raise ValueError("each fitness case must be an object")
        case_id = value.get("case_id")
        kind_value = value.get("kind")
        messages_value = value.get("messages")
        expect_value = value.get("expect")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("each fitness case must have a case_id")
        if not isinstance(kind_value, str):
            raise ValueError(f"{case_id} is missing its kind")
        if not isinstance(messages_value, list) or not messages_value:
            raise ValueError(f"{case_id} must have at least one message")
        if not isinstance(expect_value, dict):
            raise ValueError(f"{case_id} must have an expect object")
        messages: list[dict[str, str]] = []
        for message in messages_value:
            if not isinstance(message, dict):
                raise ValueError(f"{case_id} contains an invalid message")
            role, content = message.get("role"), message.get("content")
            if role not in {"system", "user", "assistant"} or not isinstance(
                content, str
            ):
                raise ValueError(f"{case_id} contains an invalid message")
            messages.append({"role": role, "content": content})
        try:
            kind = CallKind(kind_value)
        except ValueError as exc:
            raise ValueError(f"{case_id} has unknown kind {kind_value!r}") from exc
        cases.append(
            FitnessCase(
                case_id=case_id,
                kind=kind,
                messages=tuple(messages),
                expect=expect_value,
            )
        )
    validate_case_coverage(cases)
    return tuple(cases)


def validate_case_coverage(cases: Sequence[FitnessCase]) -> None:
    """Require the planned 6/3/3/3 case split and coverage of every research tool."""
    counts = {kind: sum(case.kind is kind for case in cases) for kind in CallKind}
    expected_counts = {
        CallKind.PLAN: 6,
        CallKind.EVALUATE: 3,
        CallKind.SYNTHESIZE: 3,
        CallKind.JUDGE: 3,
        CallKind.PROBE: 0,
    }
    if counts != expected_counts:
        raise ValueError(f"fitness case counts must be {expected_counts}, got {counts}")
    covered: set[str] = set()
    for case in cases:
        if case.kind is CallKind.PLAN:
            tools = case.expect.get("tools")
            if not isinstance(tools, list) or not all(
                isinstance(tool, str) for tool in tools
            ):
                raise ValueError(f"{case.case_id} must define expected tools")
            covered.update(tools)
    required_tools = set(ACTION_TOOL_NAMES)
    if covered != required_tools:
        raise ValueError(
            f"plan cases must cover every action tool: expected {required_tools}, got {covered}"
        )


def score_case(
    kind: CallKind, value: BaseModel | None, expected: Mapping[str, Any]
) -> float:
    """Return a binary task score, with invalid or missing model output scoring zero."""
    if value is None:
        return 0.0
    if kind is CallKind.PLAN and isinstance(value, ActionBatch):
        actual = {action.tool for action in value.actions}
        return float(actual == set(expected["tools"]))
    if kind is CallKind.EVALUATE and isinstance(value, BaseModel):
        return float(getattr(value, "sufficient", None) is expected["sufficient"])
    if kind is CallKind.SYNTHESIZE and isinstance(value, FitnessAnswer):
        handles = [handle for claim in value.claims for handle in claim.handles]
        allowed = set(expected["handles"])
        return float(
            bool(value.claims) and all(handle in allowed for handle in handles)
        )
    if kind is CallKind.JUDGE and isinstance(value, FitnessJudgement):
        return float(value.labels == expected["labels"])
    return 0.0


def output_model(kind: CallKind) -> type[BaseModel]:
    """Return the schema-constrained output type for one measured call kind."""
    if kind is CallKind.PLAN:
        return cast(type[BaseModel], ActionBatch)
    if kind is CallKind.EVALUATE:
        return cast(type[BaseModel], SufficiencyDecision)
    if kind is CallKind.SYNTHESIZE:
        return cast(type[BaseModel], FitnessAnswer)
    if kind is CallKind.JUDGE:
        return cast(type[BaseModel], FitnessJudgement)
    raise ValueError(f"unsupported fitness call kind: {kind.value}")


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Return the nearest-rank percentile for a non-empty sample."""
    if not values:
        return None
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def summarize(records: Sequence[FitnessRecord]) -> list[dict[str, object]]:
    """Aggregate metrics by call kind, thinking setting and output format."""
    grouped: dict[tuple[str, bool, str], list[FitnessRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.kind, record.think, record.format)].append(record)
    summary: list[dict[str, object]] = []
    for (kind, think, output_format), group in sorted(grouped.items()):
        latencies = [item.latency_ms for item in group]
        token_total = sum(item.output_tokens or 0 for item in group)
        elapsed_seconds = sum(latencies) / 1000
        summary.append(
            {
                "kind": kind,
                "think": think,
                "format": output_format,
                "valid_rate": sum(item.valid for item in group) / len(group),
                "accuracy": sum(item.score for item in group) / len(group),
                "median_latency_ms": statistics.median(latencies),
                "p95_latency_ms": percentile(latencies, 0.95),
                "output_tokens_per_second": (
                    token_total / elapsed_seconds if elapsed_seconds else None
                ),
                "runs": len(group),
            }
        )
    return summary


async def _native_plan(
    http: httpx.AsyncClient,
    settings: Settings,
    case: FitnessCase,
    *,
    think: bool,
) -> tuple[ActionBatch | None, float, int | None, int | None, str | None]:
    started = time.perf_counter()
    try:
        response = await http.post(
            "/api/chat",
            json={
                "model": settings.llm_model,
                "messages": list(case_messages(case)),
                "stream": False,
                "think": think,
                "tools": _native_tools(),
                "options": {
                    "num_ctx": settings.llm_context_tokens,
                    "num_predict": output_token_limit(CallKind.PLAN, think=think),
                    "num_gpu": GPU_MODEL_LAYER_LIMIT,
                    "seed": settings.llm_seed,
                },
            },
            timeout=settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Ollama reply must be an object")
        prompt_tokens = _token_count(payload.get("prompt_eval_count"))
        output_tokens = _token_count(payload.get("eval_count"))
        message = payload.get("message")
        calls = message.get("tool_calls") if isinstance(message, dict) else None
        if not isinstance(calls, list):
            raise ValueError("Ollama reply did not contain tool_calls")
        actions = actions_from_tool_calls(
            calls,
            max_actions=max(1, len(calls)),
        )
        return (
            ActionBatch(rationale="native tool calls", actions=actions),
            (time.perf_counter() - started) * 1000,
            prompt_tokens,
            output_tokens,
            None,
        )
    except (httpx.HTTPError, ValueError, ValidationError, TypeError) as exc:
        return (
            None,
            (time.perf_counter() - started) * 1000,
            None,
            None,
            type(exc).__name__,
        )


def _native_tools() -> list[dict[str, object]]:
    """Compatibility wrapper for the shared action-schema definitions."""
    return research_tool_definitions()


def _token_count(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


async def _gpu_memory_sampler(stop: asyncio.Event, samples: list[int]) -> None:
    while not stop.is_set():
        try:
            process = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
            if process.returncode == 0:
                values = [
                    int(line.strip())
                    for line in stdout.decode("utf-8").splitlines()
                    if line.strip().isdigit()
                ]
                if values:
                    samples.append(max(values))
        except (OSError, TimeoutError):
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.5)
        except TimeoutError:
            continue


async def _verify_model_gpu_placement(model_name: str) -> str:
    """Require Ollama to report the active generator fully resident on GPU."""
    process = await asyncio.create_subprocess_exec(
        "docker",
        "compose",
        "--profile",
        "llm",
        "exec",
        "-T",
        "ollama",
        "ollama",
        "ps",
        cwd=REPOSITORY_ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"could not verify Ollama GPU placement: {detail}")

    model_prefix = model_name.removesuffix(":latest")
    for line in stdout.decode("utf-8", errors="replace").splitlines()[1:]:
        columns = line.split()
        if columns and columns[0].removesuffix(":latest") == model_prefix:
            if "100% GPU" in line:
                return "100% GPU"
            raise RuntimeError(f"Ollama did not place all model layers on GPU: {line}")
    raise RuntimeError(f"Ollama does not report loaded model {model_name!r}")


def _write_artifact(
    output_path: Path,
    *,
    arrangement: str,
    repetitions: int,
    model: Mapping[str, object] | None,
    gpu_placement: str,
    retrieval_device: str,
    ollama_context_length: str | None,
    ollama_kv_cache_type: str | None,
    gpu_samples: Sequence[int],
    records: Sequence[FitnessRecord],
    complete: bool,
    think_repetitions: int | None = None,
    think_repair_attempts: int | None = None,
) -> dict[str, object]:
    """Atomically write current sanitized measurements, including partial runs."""
    metadata: dict[str, object] = {
        "schema_version": 1,
        "harness_version": HARNESS_VERSION,
        "complete": complete,
        "arrangement": arrangement,
        "model": model,
        "gpu_placement": gpu_placement,
        "gpu_layer_request": GPU_MODEL_LAYER_LIMIT,
        "retrieval_device": retrieval_device,
        "ollama_context_length": ollama_context_length,
        "ollama_kv_cache_type": ollama_kv_cache_type,
        "peak_gpu_memory_mib": max(gpu_samples) if gpu_samples else None,
        "repetitions": repetitions,
        "think_repetitions": think_repetitions,
        "think_repair_attempts": think_repair_attempts,
        "output_token_limits": {
            kind.value: token_limit for kind, token_limit in OUTPUT_TOKEN_LIMITS.items()
        },
        "thinking_token_allowance": THINKING_TOKEN_ALLOWANCE,
        "records": [record.as_json() for record in records],
        "summary": summarize(records),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    temporary_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary_path.replace(output_path)
    return metadata


async def run_fitness(
    *,
    arrangement: Literal["gpu-shared", "retrieval-cpu"],
    repetitions: int,
    output_path: Path,
    cases_path: Path = DEFAULT_CASES_PATH,
    think_repetitions: int | None = None,
    think_repair_attempts: int = 2,
) -> dict[str, object]:
    """Run all JSON and native-plan conditions and write sanitized measurements.

    Thinking-on calls may use fewer repetitions and repairs than thinking-off calls,
    because each one can run for minutes.
    """
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    think_repetitions = repetitions if think_repetitions is None else think_repetitions
    if think_repetitions < 1:
        raise ValueError("think_repetitions must be at least 1")
    if not 0 <= think_repair_attempts <= 5:
        raise ValueError("think_repair_attempts must be between 0 and 5")
    output_root = (REPOSITORY_ROOT / "local-reference/phase3-runs").resolve()
    resolved_output = output_path.resolve()
    if not resolved_output.is_relative_to(output_root):
        raise ValueError("output must be inside local-reference/phase3-runs")

    os.environ["RESEARCH_PLATFORM_MODEL_DEVICE"] = (
        "cuda" if arrangement == "gpu-shared" else "cpu"
    )
    settings = Settings()
    cases = load_cases(cases_path)
    records: list[FitnessRecord] = []
    gpu_samples: list[int] = []
    gpu_placement = "not-yet-verified"
    stop_sampler = asyncio.Event()
    sampler = asyncio.create_task(_gpu_memory_sampler(stop_sampler, gpu_samples))
    phase2_runtime: Phase2Runtime | None = None
    client_identity: ModelIdentity | None = None

    try:
        phase2_runtime = await create_phase2_runtime(settings)
        async with httpx.AsyncClient(
            base_url=settings.llm_base_url.rstrip("/")
        ) as http:
            llm: LLMClient = OllamaClient.from_settings(http, settings)
            client_identity = await llm.identity()
            model_identity = client_identity.model_dump(mode="json")
            warmup_response = await http.post(
                "/api/chat",
                json={
                    "model": settings.llm_model,
                    "messages": [{"role": "user", "content": "Reply OK."}],
                    "stream": False,
                    "options": {
                        "num_ctx": settings.llm_context_tokens,
                        "num_predict": 1,
                        "num_gpu": GPU_MODEL_LAYER_LIMIT,
                    },
                },
                timeout=settings.llm_timeout_seconds,
            )
            warmup_response.raise_for_status()
            gpu_placement = await _verify_model_gpu_placement(settings.llm_model)
            for case in cases:
                for think in (False, True):
                    condition_repetitions = think_repetitions if think else repetitions
                    for repetition in range(1, condition_repetitions + 1):
                        call = StructuredCall(
                            kind=case.kind,
                            messages=tuple(
                                ChatMessage(
                                    role=cast(
                                        Literal["system", "user", "assistant"],
                                        message["role"],
                                    ),
                                    content=message["content"],
                                )
                                for message in case_messages(case)
                            ),
                            output_model=output_model(case.kind),
                            think=think,
                            max_output_tokens=output_token_limit(
                                case.kind, think=think
                            ),
                            max_repair_attempts=(think_repair_attempts if think else 2),
                        )
                        started = time.perf_counter()
                        value: BaseModel | None = None
                        error_type: str | None = None
                        try:
                            result = await llm.generate(call)
                            value = result.value
                            latency_ms = result.duration_ms
                            prompt_tokens = result.prompt_tokens
                            output_tokens = result.output_tokens
                        except LLMError as exc:
                            latency_ms = (time.perf_counter() - started) * 1000
                            prompt_tokens = None
                            output_tokens = None
                            error_type = type(exc).__name__
                        score = score_case(case.kind, value, case.expect)
                        records.append(
                            FitnessRecord(
                                case_id=case.case_id,
                                kind=case.kind.value,
                                think=think,
                                format="json_schema",
                                repetition=repetition,
                                valid=value is not None,
                                score=score,
                                latency_ms=latency_ms,
                                prompt_tokens=prompt_tokens,
                                output_tokens=output_tokens,
                                error_type=error_type,
                            )
                        )
                        _write_artifact(
                            resolved_output,
                            arrangement=arrangement,
                            repetitions=repetitions,
                            think_repetitions=think_repetitions,
                            think_repair_attempts=think_repair_attempts,
                            model=model_identity,
                            gpu_placement=gpu_placement,
                            retrieval_device=os.environ[
                                "RESEARCH_PLATFORM_MODEL_DEVICE"
                            ],
                            ollama_context_length=os.environ.get(
                                "OLLAMA_CONTEXT_LENGTH"
                            ),
                            ollama_kv_cache_type=os.environ.get("OLLAMA_KV_CACHE_TYPE"),
                            gpu_samples=gpu_samples,
                            records=records,
                            complete=False,
                        )
                        if case.kind is CallKind.PLAN:
                            (
                                native,
                                native_latency,
                                native_prompt_tokens,
                                native_output_tokens,
                                native_error,
                            ) = await _native_plan(http, settings, case, think=think)
                            records.append(
                                FitnessRecord(
                                    case_id=case.case_id,
                                    kind=case.kind.value,
                                    think=think,
                                    format="native_tools",
                                    repetition=repetition,
                                    valid=native is not None,
                                    score=score_case(case.kind, native, case.expect),
                                    latency_ms=native_latency,
                                    prompt_tokens=native_prompt_tokens,
                                    output_tokens=native_output_tokens,
                                    error_type=native_error,
                                )
                            )
                            _write_artifact(
                                resolved_output,
                                arrangement=arrangement,
                                repetitions=repetitions,
                                think_repetitions=think_repetitions,
                                think_repair_attempts=think_repair_attempts,
                                model=model_identity,
                                gpu_placement=gpu_placement,
                                retrieval_device=os.environ[
                                    "RESEARCH_PLATFORM_MODEL_DEVICE"
                                ],
                                ollama_context_length=os.environ.get(
                                    "OLLAMA_CONTEXT_LENGTH"
                                ),
                                ollama_kv_cache_type=os.environ.get(
                                    "OLLAMA_KV_CACHE_TYPE"
                                ),
                                gpu_samples=gpu_samples,
                                records=records,
                                complete=False,
                            )
    finally:
        stop_sampler.set()
        await sampler
        if phase2_runtime is not None:
            await phase2_runtime.close()

    metadata = _write_artifact(
        resolved_output,
        arrangement=arrangement,
        repetitions=repetitions,
        think_repetitions=think_repetitions,
        think_repair_attempts=think_repair_attempts,
        model=(client_identity.model_dump(mode="json") if client_identity else None),
        gpu_placement=gpu_placement,
        retrieval_device=os.environ["RESEARCH_PLATFORM_MODEL_DEVICE"],
        ollama_context_length=os.environ.get("OLLAMA_CONTEXT_LENGTH"),
        ollama_kv_cache_type=os.environ.get("OLLAMA_KV_CACHE_TYPE"),
        gpu_samples=gpu_samples,
        records=records,
        complete=True,
    )
    summary = summarize(records)
    print_summary(summary, metadata["peak_gpu_memory_mib"])
    return metadata


def print_summary(summary: Sequence[Mapping[str, object]], peak_memory: object) -> None:
    """Print compact tables suitable for comparing model conditions."""
    print("kind        think format       valid accuracy median_ms p95_ms tok_per_s")
    for row in summary:
        throughput = row["output_tokens_per_second"]
        throughput_display = (
            f"{_number(throughput):>9.2f}" if throughput is not None else "        n/a"
        )
        print(
            f"{row['kind']:<11} {str(row['think']):<5} {row['format']:<12} "
            f"{_number(row['valid_rate']):>5.1%} {_number(row['accuracy']):>8.1%} "
            f"{_number(row['median_latency_ms']):>9.0f} "
            f"{_number(row['p95_latency_ms']):>6.0f} {throughput_display}"
        )
    print(
        f"peak_gpu_memory_mib={peak_memory if peak_memory is not None else 'unavailable'}"
    )


def _number(value: object) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"expected a number, got {type(value).__name__}")
    return float(value)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arrangement", choices=("gpu-shared", "retrieval-cpu"), required=True
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--think-repetitions", type=int, default=None)
    parser.add_argument("--think-repair-attempts", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(
        run_fitness(
            arrangement=arguments.arrangement,
            repetitions=arguments.repetitions,
            output_path=arguments.output,
            cases_path=arguments.cases,
            think_repetitions=arguments.think_repetitions,
            think_repair_attempts=arguments.think_repair_attempts,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
