"""Behavioral tests for external evidence text exposure."""

from datetime import UTC, datetime
from uuid import uuid4

from research_platform.config import Settings
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimResult,
    EvidenceCitation,
    ResearchMode,
    ResearchRunView,
    RunStatus,
    SupportLabel,
)
from research_platform.services.text_exposure import (
    external_text_allowed,
    redact_run_view,
)


def _run_view() -> ResearchRunView:
    return ResearchRunView(
        run_id=uuid4(),
        status=RunStatus.COMPLETED,
        mode=ResearchMode.QUICK,
        question="What did the study report?",
        answer="The study reported a result.",
        answer_outcome=AnswerOutcome.ANSWERED,
        claims=(
            ClaimResult(
                claim_id="claim-1",
                text="The first finding.",
                quote="zq7731 first quote",
                evidence=(
                    EvidenceCitation(
                        handle="E1",
                        chunk_id="chunk-1",
                        paper_id="paper-1",
                    ),
                ),
                support=SupportLabel.SUPPORTED,
            ),
            ClaimResult(
                claim_id="claim-2",
                text="The second finding.",
                quote="zq7731 second quote",
                evidence=(
                    EvidenceCitation(
                        handle="E2",
                        chunk_id="chunk-2",
                        paper_id="paper-2",
                    ),
                ),
                support=SupportLabel.SUPPORTED,
            ),
        ),
        created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )


def test_text_allowed_only_for_trusted_private_client() -> None:
    assert external_text_allowed(Settings()) is False
    assert (
        external_text_allowed(
            Settings(
                mcp_text_policy="trusted_private_client",
                evidence_access_profile="trusted_private_local",
            )
        )
        is True
    )


def test_redact_removes_every_claim_quote() -> None:
    view = _run_view()

    result = redact_run_view(view, text_allowed=False)

    assert "zq7731" not in result.model_dump_json()
    assert tuple(claim.quote for claim in result.claims) == (None, None)
    assert tuple(claim.text for claim in result.claims) == tuple(
        claim.text for claim in view.claims
    )
    assert tuple(claim.evidence for claim in result.claims) == tuple(
        claim.evidence for claim in view.claims
    )
    assert result.answer == view.answer


def test_redact_keeps_quotes_when_allowed() -> None:
    view = _run_view()

    assert redact_run_view(view, text_allowed=True) is view
