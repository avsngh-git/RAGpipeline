"""Synthesize a research answer and verify each claim against its cited passage."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from research_platform.agents.evidence import (
    EvidenceRegistry,
    neutralize,
    pack_evidence,
)
from research_platform.agents.prompts import synthesize_messages
from research_platform.agents.verification import verify_claim
from research_platform.llm.contracts import LLMClient, StructuredCall
from research_platform.llm.types import CallKind
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimResult,
    EvidenceCitation,
    RunBudgets,
    SupportLabel,
)

EvidenceHandle = Annotated[str, Field(pattern=r"^E[1-9][0-9]*$")]
_INSUFFICIENT_ANSWER = (
    "No supported claims could be verified from the available evidence."
)
# Output cap for synthesis without thinking. With thinking the call is uncapped.
_SYNTHESIS_OUTPUT_TOKENS = 2048


class DraftClaim(BaseModel):
    """One generated claim with the passage it cites and a quote copied from it.

    Field order is the order the model writes them: the quote comes before the claim
    so that the claim is written from the quote.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    handle: EvidenceHandle
    quote: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=400)


class DraftAnswer(BaseModel):
    """Structured synthesis returned by the model, in the order it is written.

    Every field is required so that constrained decoding cannot skip a step.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    relevant_handles: tuple[EvidenceHandle, ...] = Field(max_length=10)
    insufficient_evidence: bool
    claims: tuple[DraftClaim, ...] = Field(max_length=6)
    answer: str = Field(max_length=1500)


class VerifiedAnswer(BaseModel):
    """Synthesis outcome with claims mapped to registered evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    answer: str
    outcome: AnswerOutcome
    claims: tuple[ClaimResult, ...]
    rejected_claims: int = Field(ge=0)
    unsupported_claims: int = Field(ge=0)
    model_calls: int = Field(ge=0)


def decide_outcome(
    *, insufficient: bool, kept: int, rejected: int, unsupported: int
) -> AnswerOutcome:
    """Summarize evidence support after handle validation and judging."""
    if insufficient or kept == 0:
        return AnswerOutcome.INSUFFICIENT_EVIDENCE
    if rejected == 0 and unsupported == 0:
        return AnswerOutcome.ANSWERED
    return AnswerOutcome.PARTIALLY_SUPPORTED


_CITATION_MARKER = re.compile(r"\[(E[0-9]+(?:\s*,\s*E[0-9]+)*)\]")


def strip_unknown_markers(answer: str, allowed: frozenset[str]) -> str:
    """Remove citation handles that are absent from the verified claims."""

    def replace(match: re.Match[str]) -> str:
        handles = re.findall(r"E[0-9]+", match.group(1))
        retained = [handle for handle in handles if handle in allowed]
        return f"[{', '.join(retained)}]" if retained else ""

    stripped = _CITATION_MARKER.sub(replace, answer)
    stripped = re.sub(r"[ \t]+([.,;:!?])", r"\1", stripped)
    return re.sub(r"[ \t]{2,}", " ", stripped)


def _render_verified_claims(claims: list[ClaimResult]) -> str:
    """Render only retained claims, each with its verified evidence handles."""
    rendered: list[str] = []
    for claim in claims:
        handles = tuple(citation.handle for citation in claim.evidence)
        text = strip_unknown_markers(claim.text, frozenset(handles))
        rendered.append(f"{text} [{', '.join(handles)}]")
    return " ".join(rendered) if rendered else _INSUFFICIENT_ANSWER


async def answer_question(
    llm: LLMClient,
    *,
    question: str,
    registry: EvidenceRegistry,
    texts: Mapping[str, str],
    budgets: RunBudgets,
    thinking: frozenset[CallKind],
) -> VerifiedAnswer:
    """Synthesize quoted claims, then keep only those that pass the code checks.

    A claim is rejected when its handle was not registered and shown to the model,
    and counted unsupported when it fails a check in ``verify_claim``. The returned
    answer text lists only kept claims; the model's own summary is not verified and
    is not shown.
    """
    packed = pack_evidence(
        registry.refs, texts, max_tokens=budgets.max_synthesis_tokens
    )
    if not packed.included:
        return VerifiedAnswer(
            answer="No evidence was found for this question.",
            outcome=AnswerOutcome.INSUFFICIENT_EVIDENCE,
            claims=(),
            rejected_claims=0,
            unsupported_claims=0,
            model_calls=0,
        )

    think = CallKind.SYNTHESIZE in thinking
    synthesis = await llm.generate(
        StructuredCall(
            kind=CallKind.SYNTHESIZE,
            messages=synthesize_messages(question=question, packed=packed),
            output_model=DraftAnswer,
            think=think,
            max_output_tokens=None if think else _SYNTHESIS_OUTPUT_TOKENS,
            max_repair_attempts=budgets.max_model_retries,
        )
    )
    draft = synthesis.value
    if draft.insufficient_evidence or not draft.claims:
        return VerifiedAnswer(
            answer=strip_unknown_markers(draft.answer, frozenset())
            or _INSUFFICIENT_ANSWER,
            outcome=AnswerOutcome.INSUFFICIENT_EVIDENCE,
            claims=(),
            rejected_claims=0,
            unsupported_claims=0,
            model_calls=1,
        )

    shown = frozenset(packed.included)
    claims: list[ClaimResult] = []
    rejected = 0
    unsupported = 0
    for draft_claim in draft.claims:
        ref = registry.resolve(draft_claim.handle)
        if ref is None or draft_claim.handle not in shown:
            rejected += 1
            continue
        passage = neutralize(texts.get(ref.chunk_id, ""))
        if not verify_claim(draft_claim.text, draft_claim.quote, passage).passed:
            unsupported += 1
            continue
        claims.append(
            ClaimResult(
                claim_id=f"claim-{len(claims) + 1}",
                text=draft_claim.text,
                quote=draft_claim.quote,
                evidence=(
                    EvidenceCitation(
                        handle=ref.handle, chunk_id=ref.chunk_id, paper_id=ref.paper_id
                    ),
                ),
                support=SupportLabel.SUPPORTED,
            )
        )

    return VerifiedAnswer(
        answer=_render_verified_claims(claims),
        outcome=decide_outcome(
            insufficient=False,
            kept=len(claims),
            rejected=rejected,
            unsupported=unsupported,
        ),
        claims=tuple(claims),
        rejected_claims=rejected,
        unsupported_claims=unsupported,
        model_calls=1,
    )
