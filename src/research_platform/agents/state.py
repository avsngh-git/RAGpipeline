"""Checkpointable state shared by the Phase 3 research graphs."""

from __future__ import annotations

from typing import Any, TypedDict

from research_platform.agents.answering import VerifiedAnswer
from research_platform.agents.evidence import EvidenceRegistry
from research_platform.tools.research_tools import ToolLedger


class ResearchState(TypedDict):
    """Bounded, checkpoint-safe state for one research run."""

    question: str
    ledger: ToolLedger
    registry: EvidenceRegistry
    observations: list[str]
    candidate_paper_ids: list[str]
    pending_actions: list[dict[str, Any]]
    plan_round: int
    model_calls: int
    sufficient: bool
    missing: str
    answer: VerifiedAnswer | None


def initial_state(question: str) -> ResearchState:
    """Create the empty state for a new run."""
    return {
        "question": question,
        "ledger": ToolLedger(),
        "registry": EvidenceRegistry(),
        "observations": [],
        "candidate_paper_ids": [],
        "pending_actions": [],
        "plan_round": 0,
        "model_calls": 0,
        "sufficient": False,
        "missing": "",
        "answer": None,
    }
