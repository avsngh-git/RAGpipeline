"""Registered evaluation suites."""

from __future__ import annotations

from typing import Final

from research_platform.evaluation.suites.agent_dev import AgentDevSuite
from research_platform.evaluation.suites.base import Suite
from research_platform.evaluation.suites.retrieval_dev import RetrievalDevSuite
from research_platform.evaluation.suites.scripted_regression import (
    ScriptedRegressionSuite,
)
from research_platform.evaluation.suites.security_live import SecurityLiveSuite

SUITES: Final[dict[str, Suite]] = {
    AgentDevSuite.name: AgentDevSuite(),
    ScriptedRegressionSuite.name: ScriptedRegressionSuite(),
    RetrievalDevSuite.name: RetrievalDevSuite(),
    SecurityLiveSuite.name: SecurityLiveSuite(),
}
