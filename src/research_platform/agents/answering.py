"""Synthesize a research answer and verify its evidence references."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from research_platform.agents.evidence import (
    EvidenceRef,
    EvidenceRegistry,
    PackedEvidence,
    pack_evidence,
)
from research_platform.agents.prompts import judge_messages, synthesize_messages
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


class DraftClaim(BaseModel):
    """One generated claim and the evidence handles offered in support."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=1000)
    handles: tuple[EvidenceHandle, ...] = Field(min_length=1, max_length=8)


class DraftAnswer(BaseModel):
    """Structured synthesis returned by the model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    answer: str = Field(max_length=4000)
    claims: tuple[DraftClaim, ...] = Field((), max_length=8)
    insufficient_evidence: bool = False


class ClaimJudgement(BaseModel):
    """Judge label for one one-indexed claim."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim_index: int = Field(ge=1)
    label: SupportLabel
    reason: str = Field("", max_length=200)


class JudgeOutput(BaseModel):
    """Structured support judgments returned by the model."""

    model_config = ConfigDict(extra="forbid")

    judgements: tuple[ClaimJudgement, ...]


class VerifiedAnswer(BaseModel):
    """Synthesis outcome with claims mapped to registered evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    answer: str
    outcome: AnswerOutcome
    claims: tuple[ClaimResult, ...]
    rejected_claims: int = Field(ge=0)
    unsupported_claims: int = Field(ge=0)
    model_calls: int = Field(ge=0)


def check_handles(
    draft: DraftAnswer, registry: EvidenceRegistry, packed: PackedEvidence
) -> tuple[tuple[tuple[DraftClaim, tuple[EvidenceRef, ...]], ...], int]:
    """Keep only claims citing handles that were registered and shown to the model."""
    shown = frozenset(packed.included)
    checked: list[tuple[DraftClaim, tuple[EvidenceRef, ...]]] = []
    rejected = 0
    for claim in draft.claims:
        refs: list[EvidenceRef] = []
        for handle in claim.handles:
            ref = registry.resolve(handle)
            if handle not in shown or ref is None:
                break
            refs.append(ref)
        else:
            checked.append((claim, tuple(refs)))
            continue
        rejected += 1
    return tuple(checked), rejected


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
    """Synthesize, verify cited handles, then judge claim support once."""
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

    synthesis = await llm.generate(
        StructuredCall(
            kind=CallKind.SYNTHESIZE,
            messages=synthesize_messages(question=question, packed=packed),
            output_model=DraftAnswer,
            think=CallKind.SYNTHESIZE in thinking,
            max_output_tokens=2048,
            max_repair_attempts=budgets.max_model_retries,
        )
    )
    draft = synthesis.value
    if draft.insufficient_evidence:
        return VerifiedAnswer(
            answer=strip_unknown_markers(draft.answer, frozenset()),
            outcome=AnswerOutcome.INSUFFICIENT_EVIDENCE,
            claims=(),
            rejected_claims=0,
            unsupported_claims=0,
            model_calls=1,
        )

    checked, rejected = check_handles(draft, registry, packed)
    if not checked:
        return VerifiedAnswer(
            answer=_INSUFFICIENT_ANSWER,
            outcome=AnswerOutcome.INSUFFICIENT_EVIDENCE,
            claims=(),
            rejected_claims=rejected,
            unsupported_claims=0,
            model_calls=1,
        )

    indexed_claims = tuple(
        (index, claim.text, claim.handles)
        for index, (claim, _) in enumerate(checked, start=1)
    )
    judged = await llm.generate(
        StructuredCall(
            kind=CallKind.JUDGE,
            messages=judge_messages(claims=indexed_claims, packed=packed),
            output_model=JudgeOutput,
            think=CallKind.JUDGE in thinking,
            max_output_tokens=1024,
            max_repair_attempts=budgets.max_model_retries,
        )
    )

    judgements: dict[int, SupportLabel] = {}
    for judgement in judged.value.judgements:
        if 1 <= judgement.claim_index <= len(checked):
            judgements.setdefault(judgement.claim_index, judgement.label)

    claims: list[ClaimResult] = []
    unsupported = 0
    allowed: set[str] = set()
    for index, (claim, refs) in enumerate(checked, start=1):
        label = judgements.get(index, SupportLabel.UNSUPPORTED)
        if label is SupportLabel.UNSUPPORTED:
            unsupported += 1
            continue
        claims.append(
            ClaimResult(
                claim_id=f"claim-{len(claims) + 1}",
                text=claim.text,
                evidence=tuple(
                    EvidenceCitation(
                        handle=ref.handle, chunk_id=ref.chunk_id, paper_id=ref.paper_id
                    )
                    for ref in refs
                ),
                support=label,
            )
        )
        allowed.update(ref.handle for ref in refs)

    answer = (
        strip_unknown_markers(draft.answer, frozenset(allowed))
        if rejected == 0 and unsupported == 0
        else _render_verified_claims(claims)
    )
    return VerifiedAnswer(
        answer=answer,
        outcome=decide_outcome(
            insufficient=False,
            kept=len(claims),
            rejected=rejected,
            unsupported=unsupported,
        ),
        claims=tuple(claims),
        rejected_claims=rejected,
        unsupported_claims=unsupported,
        model_calls=2,
    )
