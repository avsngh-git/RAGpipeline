"""Which evidence text an external client may receive (ADR-0031)."""

from __future__ import annotations

from enum import StrEnum

from research_platform.config import Settings
from research_platform.runs.contracts import ResearchRunView
from research_platform.search.access import EvidenceAccessProfile


class TextExposurePolicy(StrEnum):
    PUBLIC_DISPLAY_ONLY = "public_display_only"
    TRUSTED_PRIVATE_CLIENT = "trusted_private_client"


def external_text_allowed(settings: Settings) -> bool:
    """Whether evidence text may be sent to an external client."""
    return (
        TextExposurePolicy(settings.mcp_text_policy)
        is TextExposurePolicy.TRUSTED_PRIVATE_CLIENT
        and settings.evidence_access_profile
        == EvidenceAccessProfile.TRUSTED_PRIVATE_LOCAL.value
    )


def redact_run_view(view: ResearchRunView, *, text_allowed: bool) -> ResearchRunView:
    """Remove claim quotes when evidence text may not leave the server."""
    if text_allowed:
        return view
    return view.model_copy(
        update={
            "claims": tuple(
                claim.model_copy(update={"quote": None}) for claim in view.claims
            )
        }
    )
