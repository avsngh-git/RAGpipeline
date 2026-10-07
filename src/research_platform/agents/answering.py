"""Synthesize a research answer and verify each claim against its cited passage."""

from __future__ import annotations

import dataclasses
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
from research_platform.observability.tracing import (
    ATTR_CLAIMS_DRAFTED,
    ATTR_CLAIMS_KEPT,
    ATTR_CLAIMS_REJECTED,
    ATTR_CLAIMS_UNSUPPORTED,
    ATTR_CLAIMS_VERDICTS,
    SPAN_SYNTHESIZE,
    SPAN_VERIFY,
    get_tracer,
    set_id_attribute,
)
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimResult,
    ClaimVerdict,
    DraftClaimOutcome,
    EvidenceCitation,
    RunBudgets,
    SupportLabel,
    SynthesisSummary,
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
    drafts: tuple[DraftClaimOutcome, ...] = ()
    synthesis: SynthesisSummary | None = None


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
    with get_tracer().start_as_current_span(SPAN_SYNTHESIZE) as synth_span:
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
        synth_span.set_attribute(ATTR_CLAIMS_DRAFTED, len(draft.claims))
        summary = SynthesisSummary(
            model_declared_insufficient=draft.insufficient_evidence,
            relevant_handles=draft.relevant_handles,
            packed_handles=packed.included,
            omitted_handles=packed.omitted,
            drafted=len(draft.claims),
        )
        if draft.insufficient_evidence or not draft.claims:
            return VerifiedAnswer(
                answer=strip_unknown_markers(draft.answer, frozenset())
                or _INSUFFICIENT_ANSWER,
                outcome=AnswerOutcome.INSUFFICIENT_EVIDENCE,
                claims=(),
                rejected_claims=0,
                unsupported_claims=0,
                model_calls=1,
                synthesis=summary,
            )

        with get_tracer().start_as_current_span(SPAN_VERIFY) as verify_span:
            shown = frozenset(packed.included)
            claims: list[ClaimResult] = []
            outcomes: list[DraftClaimOutcome] = []
            rejected = 0
            unsupported = 0
            for ordinal, draft_claim in enumerate(draft.claims, start=1):
                ref = registry.resolve(draft_claim.handle)
                if ref is None:
                    rejected += 1
                    outcomes.append(
                        _draft_outcome(
                            ordinal, draft_claim, ClaimVerdict.UNKNOWN_HANDLE
                        )
                    )
                    continue
                if draft_claim.handle not in shown:
                    rejected += 1
                    outcomes.append(
                        _draft_outcome(
                            ordinal,
                            draft_claim,
                            ClaimVerdict.NOT_SHOWN,
                            chunk_id=ref.chunk_id,
                            paper_id=ref.paper_id,
                        )
                    )
                    continue
                passage = neutralize(texts.get(ref.chunk_id, ""))
                checks = verify_claim(draft_claim.text, draft_claim.quote, passage)
                if not checks.passed:
                    unsupported += 1
                    outcomes.append(
                        _draft_outcome(
                            ordinal,
                            draft_claim,
                            ClaimVerdict.FAILED_CHECKS,
                            failed_checks=tuple(
                                check.name
                                for check in dataclasses.fields(checks)
                                if not getattr(checks, check.name)
                            ),
                            chunk_id=ref.chunk_id,
                            paper_id=ref.paper_id,
                        )
                    )
                    continue
                outcomes.append(
                    _draft_outcome(
                        ordinal,
                        draft_claim,
                        ClaimVerdict.KEPT,
                        chunk_id=ref.chunk_id,
                        paper_id=ref.paper_id,
                    )
                )
                claims.append(
                    ClaimResult(
                        claim_id=f"claim-{len(claims) + 1}",
                        text=draft_claim.text,
                        quote=draft_claim.quote,
                        evidence=(
                            EvidenceCitation(
                                handle=ref.handle,
                                chunk_id=ref.chunk_id,
                                paper_id=ref.paper_id,
                            ),
                        ),
                        support=SupportLabel.SUPPORTED,
                    )
                )

            verify_span.set_attribute(ATTR_CLAIMS_KEPT, len(claims))
            verify_span.set_attribute(ATTR_CLAIMS_REJECTED, rejected)
            verify_span.set_attribute(ATTR_CLAIMS_UNSUPPORTED, unsupported)
            set_id_attribute(
                verify_span,
                ATTR_CLAIMS_VERDICTS,
                [outcome.verdict.value for outcome in outcomes],
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
                drafts=tuple(outcomes),
                synthesis=summary,
            )


def _draft_outcome(
    ordinal: int,
    draft_claim: DraftClaim,
    verdict: ClaimVerdict,
    *,
    failed_checks: tuple[str, ...] = (),
    chunk_id: str | None = None,
    paper_id: str | None = None,
) -> DraftClaimOutcome:
    return DraftClaimOutcome(
        ordinal=ordinal,
        handle=draft_claim.handle,
        quote=draft_claim.quote,
        text=draft_claim.text,
        verdict=verdict,
        failed_checks=failed_checks,
        chunk_id=chunk_id,
        paper_id=paper_id,
    )
