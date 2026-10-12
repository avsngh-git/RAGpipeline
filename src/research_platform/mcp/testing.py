"""Deterministic state for MCP tests; never used by the running server."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any, Final, cast
from uuid import UUID

from research_platform.api.rate_limits import RateLimitSettings, TokenBucketLimiter
from research_platform.api.research_routes import ResearchAPIServices
from research_platform.config import Settings
from research_platform.runs.memory import InMemoryRunStore
from research_platform.runs.runner import ServingIdentity
from research_platform.services.capabilities import Phase2APIServices
from research_platform.tools.fakes import (
    FakeCorpus,
    FakePaper,
    FakePassage,
    fake_services,
)

SAMPLE_SNAPSHOT_ID: Final = UUID("00000000-0000-0000-0000-000000000001")
SAMPLE_PROFILE_ID: Final = "sha256:" + "a" * 64
SAMPLE_PAPER_A: Final = "W100"
SAMPLE_PAPER_B: Final = "W200"
SAMPLE_PAPER_C: Final = "W300"


def sample_corpus() -> FakeCorpus:
    """Create the standard compact corpus for MCP protocol tests."""
    return FakeCorpus(
        snapshot_id=SAMPLE_SNAPSHOT_ID,
        papers=(
            FakePaper(SAMPLE_PAPER_A, "Retrieval paper A", 2021),
            FakePaper(SAMPLE_PAPER_B, "Retrieval paper B", 2023),
            FakePaper(SAMPLE_PAPER_C, "Other paper C", 2024),
        ),
        passages=(
            FakePassage(
                "chunk-a1", SAMPLE_PAPER_A, "Hybrid retrieval improves recall."
            ),
            FakePassage("chunk-a2", SAMPLE_PAPER_A, "Dense retrieval baseline."),
            FakePassage(
                "chunk-b1", SAMPLE_PAPER_B, "Hybrid retrieval supports evidence."
            ),
            FakePassage("chunk-c1", SAMPLE_PAPER_C, "Unrelated ranking result."),
        ),
        citations=(
            (SAMPLE_PAPER_A, SAMPLE_PAPER_B),
            (SAMPLE_PAPER_B, SAMPLE_PAPER_C),
            (SAMPLE_PAPER_C, SAMPLE_PAPER_A),
            (SAMPLE_PAPER_C, SAMPLE_PAPER_B),
        ),
    )


class RecordingExecutor:
    """Accepts research-run submissions without running them."""

    def __init__(self) -> None:
        self.submissions: list[UUID] = []

    async def submit(self, run_id: UUID, *, request_id: str | None = None) -> None:
        self.submissions.append(run_id)


def make_settings(
    *,
    text_policy: str = "public_display_only",
    evidence_access_profile: str = "trusted_private_local",
) -> Settings:
    """Build isolated settings for MCP tests."""
    return Settings(
        environment="test",
        database_url="postgresql://test:test@localhost:5432/research_test",
        qdrant_url="http://localhost:26333",
        evidence_access_profile=evidence_access_profile,
        mcp_text_policy=text_policy,
    )


def fake_state(
    corpus: FakeCorpus | None = None,
    *,
    settings: Settings | None = None,
    store: InMemoryRunStore | None = None,
    rate_limits: Mapping[str, str] | None = None,
) -> SimpleNamespace:
    """Build the app-state fields needed by MCP calls and protocol tests."""
    search, papers, citations, related = fake_services(corpus or sample_corpus())
    limits = RateLimitSettings.from_env(rate_limits or {})
    active_settings = settings or make_settings()
    return SimpleNamespace(
        settings=active_settings,
        rate_limit_settings=limits,
        rate_limiter=TokenBucketLimiter(limits),
        phase2_services=Phase2APIServices(
            search=search,
            papers=papers,
            citations=citations,
            related=related,
        ),
        research_services=ResearchAPIServices(
            store=store or InMemoryRunStore(),
            executor=cast(Any, RecordingExecutor()),
            serving=ServingIdentity(
                SAMPLE_SNAPSHOT_ID, SAMPLE_PROFILE_ID, generation=1
            ),
        ),
    )
