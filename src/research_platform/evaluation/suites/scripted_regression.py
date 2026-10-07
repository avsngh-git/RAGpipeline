"""Phase 3 synthetic scripted regression evaluation suite."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from research_platform.agents.prompts import PROMPT_VERSIONS
from research_platform.agents.tool_schemas import tool_schema_digest
from research_platform.evaluation.experiments import (
    DatasetIdentity,
    ExperimentOutcome,
    file_sha256,
)
from research_platform.evaluation.phase3_regression import (
    load_cases,
    load_corpus,
    run_case,
)
from research_platform.evaluation.suites.base import SuiteContext

CASE_PATH = (
    Path(__file__).resolve().parents[4] / "benchmarks/phase3/regression-cases-v2.json"
)


class ScriptedRegressionSuite:
    name = "scripted-regression"

    def dataset(self, options: Mapping[str, str]) -> DatasetIdentity:
        return DatasetIdentity("phase3-regression", "v2", file_sha256(CASE_PATH))

    async def run(self, context: SuiteContext) -> ExperimentOutcome:
        cases = load_cases(CASE_PATH)
        corpus = load_corpus(CASE_PATH)
        failures: Counter[str] = Counter()
        passed = 0
        for case in cases:
            result = await run_case(case, corpus)
            context.writer.append(
                {
                    "item_id": case.case_id,
                    "category": case.category,
                    "passed": result.passed,
                    "mismatch_count": len(result.mismatches),
                }
            )
            if result.passed:
                passed += 1
            else:
                failures[case.category] += 1
        count = len(cases)
        return ExperimentOutcome(
            configuration_id=None,
            configuration={"case_file": "benchmarks/phase3/regression-cases-v2.json"},
            versions={f"prompt.{key}": value for key, value in PROMPT_VERSIONS.items()}
            | {"tool_schema": tool_schema_digest()},
            random_seed=None,
            metrics={"cases": count, "passed": passed, "pass_rate": passed / count},
            failures=dict(failures),
            item_count=context.writer.count,
        )
