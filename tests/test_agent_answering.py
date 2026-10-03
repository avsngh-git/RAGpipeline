"""Synthesis validates evidence handles before judging claims."""

from __future__ import annotations

import json

import pytest

from research_platform.agents.answering import (
    DraftAnswer,
    VerifiedAnswer,
    answer_question,
    strip_unknown_markers,
)
from research_platform.agents.evidence import EvidenceRegistry
from research_platform.llm.contracts import LLMInvalidOutput
from research_platform.llm.scripted import ScriptedLLM, ScriptedReply
from research_platform.llm.types import CallKind
from research_platform.runs.contracts import AnswerOutcome, RunBudgets, SupportLabel
from research_platform.tools.research_tools import CollectedEvidence


def _registry(
    *, long_second_title: bool = False
) -> tuple[EvidenceRegistry, dict[str, str]]:
    items = (
        CollectedEvidence(
            chunk_id="chunk-1",
            paper_id="W1",
            text="Synthetic passage one.",
            title="Synthetic paper one",
            publication_year=2021,
            kind="prose",
            source_location={},
            reranker_score=None,
        ),
        CollectedEvidence(
            chunk_id="chunk-2",
            paper_id="W2",
            text="Synthetic passage two.",
            title="Synthetic paper two" + (" title" * 500 if long_second_title else ""),
            publication_year=2022,
            kind="prose",
            source_location={},
            reranker_score=None,
        ),
        CollectedEvidence(
            chunk_id="chunk-3",
            paper_id="W3",
            text="Synthetic passage three.",
            title="Synthetic paper three",
            publication_year=2023,
            kind="prose",
            source_location={},
            reranker_score=None,
        ),
    )
    registry, _ = EvidenceRegistry().register(items, max_passages=3)
    texts = {item.chunk_id: item.text for item in items}
    return registry, texts


def _reply(kind: CallKind, value: dict[str, object]) -> ScriptedReply:
    return ScriptedReply(kind=kind, content=json.dumps(value))


def _draft(
    claims: list[dict[str, object]],
    *,
    answer: str = "Synthetic answer.",
    insufficient: bool = False,
) -> ScriptedReply:
    return _reply(
        CallKind.SYNTHESIZE,
        {
            "answer": answer,
            "claims": claims,
            "insufficient_evidence": insufficient,
        },
    )


def _judge(*judgements: tuple[int, str]) -> ScriptedReply:
    return _reply(
        CallKind.JUDGE,
        {
            "judgements": [
                {"claim_index": index, "label": label, "reason": "Synthetic reason."}
                for index, label in judgements
            ]
        },
    )


async def _answer(
    replies: list[ScriptedReply],
    *,
    registry: EvidenceRegistry | None = None,
    texts: dict[str, str] | None = None,
    budgets: RunBudgets | None = None,
    thinking: frozenset[CallKind] = frozenset(),
) -> tuple[VerifiedAnswer, ScriptedLLM]:
    if registry is None or texts is None:
        registry, texts = _registry()
    llm = ScriptedLLM(replies)
    result = await answer_question(
        llm,
        question="Synthetic research question?",
        registry=registry,
        texts=texts,
        budgets=budgets or RunBudgets(),
        thinking=thinking,
    )
    return result, llm


@pytest.mark.anyio
async def test_all_claims_supported_gives_answered() -> None:
    result, llm = await _answer(
        [
            _draft(
                [
                    {"text": "First synthetic finding.", "handles": ["E1"]},
                    {"text": "Second synthetic finding.", "handles": ["E2"]},
                ],
                answer="First [E1]. Second [E2].",
            ),
            _judge((1, "supported"), (2, "supported")),
        ]
    )

    assert result.outcome is AnswerOutcome.ANSWERED
    assert [claim.claim_id for claim in result.claims] == ["claim-1", "claim-2"]
    assert [claim.support for claim in result.claims] == [
        SupportLabel.SUPPORTED,
        SupportLabel.SUPPORTED,
    ]
    assert result.answer == "First [E1]. Second [E2]."
    assert result.model_calls == 2
    assert llm.remaining == 0


@pytest.mark.anyio
async def test_fabricated_handle_rejects_only_that_claim() -> None:
    result, llm = await _answer(
        [
            _draft(
                [
                    {"text": "Grounded synthetic finding.", "handles": ["E1"]},
                    {"text": "Fabricated synthetic finding.", "handles": ["E99"]},
                ],
                answer="Grounded synthetic finding [E1]. Fabricated synthetic finding [E99].",
            ),
            _judge((1, "supported")),
        ]
    )

    assert result.rejected_claims == 1
    assert result.outcome is AnswerOutcome.PARTIALLY_SUPPORTED
    assert [claim.text for claim in result.claims] == ["Grounded synthetic finding."]
    assert result.answer == "Grounded synthetic finding. [E1]"
    assert "Fabricated synthetic finding" not in result.answer
    assert llm.calls[1].messages[1].content.find("Grounded synthetic finding.") >= 0
    assert "Fabricated synthetic finding." not in llm.calls[1].messages[1].content


@pytest.mark.anyio
async def test_known_but_omitted_handle_is_rejected() -> None:
    registry, texts = _registry(long_second_title=True)
    result, llm = await _answer(
        [
            _draft([{"text": "Omitted synthetic finding.", "handles": ["E2"]}]),
        ],
        registry=registry,
        texts=texts,
        budgets=RunBudgets(max_synthesis_tokens=500),
    )

    assert "E2" in registry.handles()
    assert result.rejected_claims == 1
    assert result.outcome is AnswerOutcome.INSUFFICIENT_EVIDENCE
    assert result.claims == ()
    assert len(llm.calls) == 1


@pytest.mark.anyio
async def test_every_claim_fabricated_gives_insufficient_and_skips_judge() -> None:
    result, llm = await _answer(
        [
            _draft(
                [{"text": "Fabricated synthetic finding.", "handles": ["E99"]}],
                answer="Unverified statement [E99].",
            )
        ]
    )

    assert result.outcome is AnswerOutcome.INSUFFICIENT_EVIDENCE
    assert result.rejected_claims == 1
    assert result.model_calls == 1
    assert (
        result.answer
        == "No supported claims could be verified from the available evidence."
    )
    assert llm.remaining == 0
    assert len(llm.calls) == 1


@pytest.mark.anyio
async def test_unsupported_claim_is_dropped_and_outcome_partial() -> None:
    result, _ = await _answer(
        [
            _draft(
                [
                    {"text": "Supported synthetic finding.", "handles": ["E1"]},
                    {"text": "Unsupported synthetic finding.", "handles": ["E2"]},
                ],
                answer="Supported statement [E1]. Unsupported statement [E2].",
            ),
            _judge((1, "supported"), (2, "unsupported")),
        ]
    )

    assert result.outcome is AnswerOutcome.PARTIALLY_SUPPORTED
    assert [claim.text for claim in result.claims] == ["Supported synthetic finding."]
    assert result.unsupported_claims == 1
    assert result.answer == "Supported synthetic finding. [E1]"
    assert "Unsupported synthetic finding" not in result.answer


@pytest.mark.anyio
async def test_every_unsupported_claim_gives_insufficient_evidence() -> None:
    result, _ = await _answer(
        [
            _draft(
                [{"text": "Unsupported synthetic finding.", "handles": ["E1"]}],
                answer="Unsupported statement [E1].",
            ),
            _judge((1, "unsupported")),
        ]
    )

    assert result.outcome is AnswerOutcome.INSUFFICIENT_EVIDENCE
    assert result.claims == ()
    assert result.unsupported_claims == 1
    assert (
        result.answer
        == "No supported claims could be verified from the available evidence."
    )
    assert "Unsupported statement" not in result.answer


@pytest.mark.anyio
async def test_missing_judgement_counts_as_unsupported() -> None:
    result, _ = await _answer(
        [
            _draft(
                [
                    {"text": "Judged synthetic finding.", "handles": ["E1"]},
                    {"text": "Unjudged synthetic finding.", "handles": ["E2"]},
                ]
            ),
            _judge((1, "supported")),
        ]
    )

    assert result.unsupported_claims == 1
    assert [claim.text for claim in result.claims] == ["Judged synthetic finding."]
    assert result.outcome is AnswerOutcome.PARTIALLY_SUPPORTED


@pytest.mark.anyio
async def test_duplicate_and_out_of_range_judgements() -> None:
    result, _ = await _answer(
        [
            _draft(
                [
                    {"text": "First synthetic finding.", "handles": ["E1"]},
                    {"text": "Second synthetic finding.", "handles": ["E2"]},
                ]
            ),
            _judge((1, "supported"), (1, "unsupported"), (99, "unsupported")),
        ]
    )

    assert [claim.text for claim in result.claims] == ["First synthetic finding."]
    assert result.unsupported_claims == 1


@pytest.mark.anyio
async def test_insufficient_flag_returns_no_claims() -> None:
    result, llm = await _answer(
        [
            _draft(
                [{"text": "Draft finding.", "handles": ["E1"]}],
                answer="Evidence is insufficient [E99].",
                insufficient=True,
            )
        ]
    )

    assert result.outcome is AnswerOutcome.INSUFFICIENT_EVIDENCE
    assert result.answer == "Evidence is insufficient."
    assert result.claims == ()
    assert result.model_calls == 1
    assert len(llm.calls) == 1


@pytest.mark.anyio
async def test_no_packed_evidence_makes_no_model_call() -> None:
    result, llm = await _answer([], registry=EvidenceRegistry(), texts={})

    assert result.outcome is AnswerOutcome.INSUFFICIENT_EVIDENCE
    assert result.answer == "No evidence was found for this question."
    assert result.model_calls == 0
    assert llm.calls == []


@pytest.mark.anyio
async def test_claims_are_renumbered_after_drops() -> None:
    result, _ = await _answer(
        [
            _draft(
                [
                    {"text": "Dropped synthetic finding.", "handles": ["E1"]},
                    {"text": "Kept synthetic finding.", "handles": ["E2"]},
                ]
            ),
            _judge((1, "unsupported"), (2, "partial")),
        ]
    )

    assert len(result.claims) == 1
    assert result.claims[0].claim_id == "claim-1"
    assert result.claims[0].text == "Kept synthetic finding."
    assert result.claims[0].support is SupportLabel.PARTIAL


def test_strip_unknown_markers() -> None:
    answer = "One [E1]. Mixed [E1, E2]. Unknown [E9]. Invalid [E0]. Leading zero [E01]."

    assert strip_unknown_markers(answer, frozenset({"E1"})) == (
        "One [E1]. Mixed [E1]. Unknown. Invalid. Leading zero."
    )

    assert strip_unknown_markers("Mixed [E1, E0].", frozenset({"E1"})) == (
        "Mixed [E1]."
    )


def test_draft_answer_schema_has_handle_pattern() -> None:
    schema = json.dumps(DraftAnswer.model_json_schema())

    assert '"pattern": "^E[1-9][0-9]*$"' in schema


@pytest.mark.anyio
async def test_thinking_flag_follows_settings() -> None:
    _, llm = await _answer(
        [
            _draft([{"text": "Synthetic finding.", "handles": ["E1"]}]),
            _judge((1, "supported")),
        ],
        thinking=frozenset({CallKind.SYNTHESIZE}),
    )

    assert [call.think for call in llm.calls] == [True, False]


@pytest.mark.anyio
async def test_invalid_model_output_propagates() -> None:
    llm = ScriptedLLM([ScriptedReply(kind=CallKind.SYNTHESIZE, content="not-json")])
    registry, texts = _registry()

    with pytest.raises(LLMInvalidOutput):
        await answer_question(
            llm,
            question="Synthetic research question?",
            registry=registry,
            texts=texts,
            budgets=RunBudgets(),
            thinking=frozenset(),
        )
