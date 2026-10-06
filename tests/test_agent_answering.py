"""Synthesis validates evidence handles, then verifies each claim against its quote."""

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
from research_platform.runs.contracts import (
    AnswerOutcome,
    ClaimVerdict,
    RunBudgets,
    SupportLabel,
)
from research_platform.tools.research_tools import CollectedEvidence

_PASSAGES = (
    "Synthetic passage one reports a retrieval gain of 4.5 points on dataset A.",
    "Synthetic passage two finds that reranking helps short queries.",
    "Synthetic passage three describes the evaluation protocol.",
)
_QUOTE_ONE = _PASSAGES[0]
_QUOTE_TWO = _PASSAGES[1]


def _registry(
    *, long_second_title: bool = False
) -> tuple[EvidenceRegistry, dict[str, str]]:
    items = tuple(
        CollectedEvidence(
            chunk_id=f"chunk-{index}",
            paper_id=f"W{index}",
            text=text,
            title=f"Synthetic paper {index}"
            + (" title" * 500 if long_second_title and index == 2 else ""),
            publication_year=2020 + index,
            kind="prose",
            source_location={},
            reranker_score=None,
        )
        for index, text in enumerate(_PASSAGES, start=1)
    )
    registry, _ = EvidenceRegistry().register(items, max_passages=3)
    texts = {item.chunk_id: item.text for item in items}
    return registry, texts


def _claim(handle: str, quote: str, text: str) -> dict[str, object]:
    return {"handle": handle, "quote": quote, "text": text}


def _draft(
    claims: list[dict[str, object]],
    *,
    answer: str = "Synthetic answer.",
    insufficient: bool = False,
) -> ScriptedReply:
    relevant = list(dict.fromkeys(str(claim["handle"]) for claim in claims))
    return ScriptedReply(
        kind=CallKind.SYNTHESIZE,
        content=json.dumps(
            {
                "relevant_handles": relevant,
                "insufficient_evidence": insufficient,
                "claims": claims,
                "answer": answer,
            }
        ),
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
async def test_all_claims_verified_gives_answered() -> None:
    result, llm = await _answer(
        [
            _draft(
                [
                    _claim(
                        "E1", _QUOTE_ONE, "Retrieval gained 4.5 points on dataset A."
                    ),
                    _claim("E2", _QUOTE_TWO, "Reranking helps short queries."),
                ],
                answer="A summary that is never shown.",
            )
        ]
    )

    assert result.outcome is AnswerOutcome.ANSWERED
    assert [claim.claim_id for claim in result.claims] == ["claim-1", "claim-2"]
    assert [claim.quote for claim in result.claims] == [_QUOTE_ONE, _QUOTE_TWO]
    assert [claim.support for claim in result.claims] == [
        SupportLabel.SUPPORTED,
        SupportLabel.SUPPORTED,
    ]
    assert result.answer == (
        "Retrieval gained 4.5 points on dataset A. [E1] "
        "Reranking helps short queries. [E2]"
    )
    assert result.model_calls == 1
    assert llm.remaining == 0


@pytest.mark.anyio
async def test_fabricated_handle_rejects_only_that_claim() -> None:
    result, llm = await _answer(
        [
            _draft(
                [
                    _claim(
                        "E1", _QUOTE_ONE, "Retrieval gained 4.5 points on dataset A."
                    ),
                    _claim("E99", _QUOTE_ONE, "Fabricated synthetic finding."),
                ]
            )
        ]
    )

    assert result.rejected_claims == 1
    assert result.unsupported_claims == 0
    assert result.outcome is AnswerOutcome.PARTIALLY_SUPPORTED
    assert [claim.text for claim in result.claims] == [
        "Retrieval gained 4.5 points on dataset A."
    ]
    assert "Fabricated synthetic finding" not in result.answer
    assert len(llm.calls) == 1


@pytest.mark.anyio
async def test_known_but_omitted_handle_is_rejected() -> None:
    registry, texts = _registry(long_second_title=True)
    result, llm = await _answer(
        [_draft([_claim("E2", _QUOTE_TWO, "Reranking helps short queries.")])],
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
async def test_every_claim_fabricated_gives_insufficient() -> None:
    result, llm = await _answer(
        [
            _draft(
                [_claim("E99", _QUOTE_ONE, "Fabricated synthetic finding.")],
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


@pytest.mark.anyio
async def test_quote_missing_from_passage_drops_claim() -> None:
    result, _ = await _answer(
        [
            _draft(
                [
                    _claim(
                        "E1", _QUOTE_ONE, "Retrieval gained 4.5 points on dataset A."
                    ),
                    _claim(
                        "E2",
                        "Reranking always helps every query type.",
                        "Reranking always helps every query type.",
                    ),
                ]
            )
        ]
    )

    assert result.outcome is AnswerOutcome.PARTIALLY_SUPPORTED
    assert result.unsupported_claims == 1
    assert [claim.handle for claim in result.claims[0].evidence] == ["E1"]
    assert "every query type" not in result.answer


@pytest.mark.anyio
async def test_quote_from_another_passage_drops_claim() -> None:
    result, _ = await _answer(
        [
            _draft(
                [_claim("E2", _QUOTE_ONE, "Retrieval gained 4.5 points on dataset A.")]
            )
        ]
    )

    assert result.outcome is AnswerOutcome.INSUFFICIENT_EVIDENCE
    assert result.unsupported_claims == 1
    assert result.claims == ()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "text",
    [
        "Retrieval gained 7.5 points on dataset A.",
        "Retrieval significantly gained 4.5 points on dataset A.",
        "Dense encoders outperform sparse baselines on multilingual benchmarks.",
        "Retrieval gained 4.5 points on dataset A [E1].",
    ],
    ids=["invented-number", "added-intensifier", "drifted", "handle-in-text"],
)
async def test_claim_beyond_its_quote_is_dropped(text: str) -> None:
    result, _ = await _answer([_draft([_claim("E1", _QUOTE_ONE, text)])])

    assert result.outcome is AnswerOutcome.INSUFFICIENT_EVIDENCE
    assert result.unsupported_claims == 1
    assert result.claims == ()


@pytest.mark.anyio
async def test_insufficient_flag_returns_no_claims() -> None:
    result, llm = await _answer(
        [
            _draft(
                [_claim("E1", _QUOTE_ONE, "Retrieval gained 4.5 points on dataset A.")],
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
                    _claim(
                        "E1", _QUOTE_ONE, "Retrieval gained 9.9 points on dataset A."
                    ),
                    _claim("E2", _QUOTE_TWO, "Reranking helps short queries."),
                ]
            )
        ]
    )

    assert len(result.claims) == 1
    assert result.claims[0].claim_id == "claim-1"
    assert result.claims[0].text == "Reranking helps short queries."


def test_strip_unknown_markers() -> None:
    answer = "One [E1]. Mixed [E1, E2]. Unknown [E9]. Invalid [E0]. Leading zero [E01]."

    assert strip_unknown_markers(answer, frozenset({"E1"})) == (
        "One [E1]. Mixed [E1]. Unknown. Invalid. Leading zero."
    )

    assert strip_unknown_markers("Mixed [E1, E0].", frozenset({"E1"})) == (
        "Mixed [E1]."
    )


def test_draft_answer_schema_orders_fields_as_the_steps() -> None:
    schema = DraftAnswer.model_json_schema()

    assert '"pattern": "^E[1-9][0-9]*$"' in json.dumps(schema)
    assert list(schema["properties"]) == [
        "relevant_handles",
        "insufficient_evidence",
        "claims",
        "answer",
    ]
    assert schema["required"] == list(schema["properties"])
    assert list(schema["$defs"]["DraftClaim"]["properties"]) == [
        "handle",
        "quote",
        "text",
    ]


@pytest.mark.anyio
async def test_thinking_uncaps_synthesis_output() -> None:
    _, thinking_llm = await _answer(
        [
            _draft(
                [_claim("E1", _QUOTE_ONE, "Retrieval gained 4.5 points on dataset A.")]
            )
        ],
        thinking=frozenset({CallKind.SYNTHESIZE}),
    )
    _, plain_llm = await _answer(
        [
            _draft(
                [_claim("E1", _QUOTE_ONE, "Retrieval gained 4.5 points on dataset A.")]
            )
        ]
    )

    assert [(call.think, call.max_output_tokens) for call in thinking_llm.calls] == [
        (True, None)
    ]
    assert [(call.think, call.max_output_tokens) for call in plain_llm.calls] == [
        (False, 2048)
    ]


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


@pytest.mark.anyio
async def test_drafts_record_unknown_handle() -> None:
    result, _ = await _answer(
        [
            _draft(
                [
                    _claim(
                        "E1", _QUOTE_ONE, "Retrieval gained 4.5 points on dataset A."
                    ),
                    _claim("E9", "invented quote text here", "Invented claim."),
                ]
            )
        ]
    )

    assert [draft.verdict for draft in result.drafts] == [
        ClaimVerdict.KEPT,
        ClaimVerdict.UNKNOWN_HANDLE,
    ]
    assert result.drafts[1].ordinal == 2
    assert result.drafts[1].chunk_id is None
    assert result.drafts[0].chunk_id == "chunk-1"
    assert result.drafts[0].paper_id == "W1"


@pytest.mark.anyio
async def test_drafts_record_not_shown_handle() -> None:
    registry, texts = _registry(long_second_title=True)
    result, _ = await _answer(
        [_draft([_claim("E2", _QUOTE_TWO, "Reranking helps short queries.")])],
        registry=registry,
        texts=texts,
        budgets=RunBudgets(max_synthesis_tokens=500),
    )

    assert [draft.verdict for draft in result.drafts] == [ClaimVerdict.NOT_SHOWN]
    assert result.drafts[0].chunk_id == "chunk-2"
    assert result.synthesis is not None
    assert "E2" in result.synthesis.omitted_handles


@pytest.mark.anyio
async def test_drafts_record_failed_check_names() -> None:
    result, _ = await _answer(
        [
            _draft(
                [
                    _claim(
                        "E1",
                        "a sentence that does not occur in the passage",
                        "Retrieval gained points.",
                    )
                ]
            )
        ]
    )

    assert result.drafts[0].verdict is ClaimVerdict.FAILED_CHECKS
    assert "quote_found" in result.drafts[0].failed_checks
    assert result.unsupported_claims == 1


@pytest.mark.anyio
async def test_drafts_record_kept() -> None:
    result, _ = await _answer(
        [
            _draft(
                [_claim("E1", _QUOTE_ONE, "Retrieval gained 4.5 points on dataset A.")]
            )
        ]
    )

    assert len(result.drafts) == 1
    assert result.drafts[0].verdict is ClaimVerdict.KEPT
    assert result.drafts[0].failed_checks == ()
    assert result.drafts[0].quote == _QUOTE_ONE


@pytest.mark.anyio
async def test_synthesis_summary_records_declared_insufficient() -> None:
    result, _ = await _answer([_draft([], insufficient=True, answer="Not answerable.")])

    assert result.drafts == ()
    assert result.synthesis is not None
    assert result.synthesis.model_declared_insufficient is True
    assert result.synthesis.drafted == 0
    assert result.synthesis.packed_handles == ("E1", "E2", "E3")
