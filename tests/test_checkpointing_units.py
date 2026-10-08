"""Fast checks for LangGraph checkpoint configuration helpers."""

import logging
from uuid import UUID

import pytest
from psycopg.conninfo import conninfo_to_dict

from research_platform.runs.checkpointing import checkpoint_conninfo, thread_config


def test_conninfo_sets_search_path_and_keeps_credentials() -> None:
    for database_url in (
        "postgresql://research:secret@localhost:5432/research_test",
        "postgresql://research:secret@localhost:5432/research_test?sslmode=disable",
    ):
        conninfo = conninfo_to_dict(checkpoint_conninfo(database_url))

        assert conninfo["user"] == "research"
        assert conninfo["password"] == "secret"
        assert conninfo["host"] == "localhost"
        assert conninfo["dbname"] == "research_test"
        assert conninfo["options"] == "-c search_path=langgraph"
        if "?" in database_url:
            assert conninfo["sslmode"] == "disable"


def test_thread_config_uses_run_id() -> None:
    run_id = UUID("2e0d7d17-926c-4e7e-a679-837fb723c669")

    assert thread_config(run_id) == {"configurable": {"thread_id": str(run_id)}}


def test_verified_answer_with_drafts_round_trips_through_checkpoint_serializer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from research_platform.agents.answering import VerifiedAnswer
    from research_platform.runs.checkpointing import checkpoint_serializer
    from research_platform.runs.contracts import (
        AnswerOutcome,
        ClaimVerdict,
        DraftClaimOutcome,
        SynthesisSummary,
    )

    answer = VerifiedAnswer(
        answer="No supported claims could be verified from the available evidence.",
        outcome=AnswerOutcome.INSUFFICIENT_EVIDENCE,
        claims=(),
        rejected_claims=0,
        unsupported_claims=1,
        model_calls=1,
        drafts=(
            DraftClaimOutcome(
                ordinal=1,
                handle="E1",
                quote="a quote",
                text="a claim",
                verdict=ClaimVerdict.FAILED_CHECKS,
                failed_checks=("quote_found",),
                chunk_id="chunk-1",
                paper_id="W1",
            ),
        ),
        synthesis=SynthesisSummary(
            model_declared_insufficient=False,
            relevant_handles=("E1",),
            packed_handles=("E1",),
            drafted=1,
        ),
    )
    serializer = checkpoint_serializer()

    with caplog.at_level(logging.WARNING):
        restored = serializer.loads_typed(serializer.dumps_typed(answer))

    assert restored == answer
    assert "Blocked deserialization" not in caplog.text
