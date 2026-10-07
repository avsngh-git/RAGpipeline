"""Registered evaluation suites."""

from __future__ import annotations

from typing import Final

from research_platform.evaluation.suites.base import Suite
from research_platform.evaluation.suites.scripted_regression import (
    ScriptedRegressionSuite,
)
from research_platform.evaluation.suites.security_live import SecurityLiveSuite

SUITES: Final[dict[str, Suite]] = {
    ScriptedRegressionSuite.name: ScriptedRegressionSuite(),
    SecurityLiveSuite.name: SecurityLiveSuite(),
}
