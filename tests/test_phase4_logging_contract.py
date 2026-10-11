"""Phase 4 structured logging and text privacy contract."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from pathlib import Path

from research_platform.evaluation.phase3_regression import (
    load_cases,
    load_corpus,
    run_case,
)
from research_platform.observability.logging_config import JsonFormatter


def test_run_logs_have_run_fields_and_no_text() -> None:
    async def exercise() -> None:
        cases_path = (
            Path(__file__).parents[1] / "benchmarks/phase3/regression-cases-v2.json"
        )
        cases = load_cases(cases_path)
        corpus = load_corpus(cases_path)
        case = next(item for item in cases if item.case_id == "route-01-search-path")
        # The scripted searches differ from the marker question, so they run after
        # the first plan's whole-question searches.
        case = dataclasses.replace(
            case,
            request=case.request.model_copy(
                update={"question": "zq7731 private question marker"}
            ),
            expect={
                **case.expect,
                "tools": ["search_papers", "search_evidence"] * 2,
                "tool_statuses": {"succeeded": 4, "cached": 0, "rejected": 0},
            },
        )

        lines: list[str] = []

        class CollectingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                lines.append(JsonFormatter().format(record))

        handler = CollectingHandler(level=logging.INFO)
        root_logger = logging.getLogger()
        original_level = root_logger.level
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)
        try:
            await run_case(case, corpus)
        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(original_level)

        finished = [
            line for line in lines if '"message": "research_run_finished"' in line
        ]
        assert len(finished) == 1
        payload = json.loads(finished[0])
        assert "run_id" in payload
        assert payload["mode"] == "deep_research"
        assert payload["status"] == "completed"
        assert "duration_seconds" in payload
        assert payload["tool_calls"] == 4
        assert "model_calls" in payload
        assert all(
            "zq7731" not in line
            and "retrieval improves ranking with evidence and citations" not in line
            for line in lines
        )

    asyncio.run(exercise())
