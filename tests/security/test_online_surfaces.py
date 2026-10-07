"""Scripted security cases for the Phase 3.5 online-ingestion surfaces."""

from __future__ import annotations

import pytest

from research_platform.evaluation.phase35_regression import (
    case_abstract_requests_unknown_paper,
)


@pytest.mark.anyio
async def test_injected_unknown_paper_is_refused_and_never_queued() -> None:
    result = await case_abstract_requests_unknown_paper()

    assert result.passed, "; ".join(result.mismatches)
