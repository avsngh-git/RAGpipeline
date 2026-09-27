"""Apply complete-item, per-paper and whole-context evidence result budgets."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from research_platform.search.contracts import (
    DEFAULT_SEARCH_LIMITS,
    EvidenceHit,
    PaperHit,
)
from research_platform.search.profiles import SelectionRules

EvidenceBudgetReason = Literal[
    "result_item_limit",
    "per_paper_limit",
    "result_character_budget",
    "result_token_budget",
]
_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


@dataclass(frozen=True)
class EvidenceBudgetOmission:
    """A complete source-linked hit omitted by a configured result budget."""

    chunk_id: str
    paper_id: str
    original_rank: int
    source_evidence_ids: tuple[str, ...]
    reasons: tuple[EvidenceBudgetReason, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, str) or not self.chunk_id.strip():
            raise ValueError("chunk_id must be non-empty")
        if not isinstance(self.paper_id, str) or not self.paper_id.strip():
            raise ValueError("paper_id must be non-empty")
        if (
            isinstance(self.original_rank, bool)
            or not isinstance(self.original_rank, int)
            or self.original_rank < 1
        ):
            raise ValueError("original_rank must be a positive integer")
        if (
            not isinstance(self.source_evidence_ids, tuple)
            or not self.source_evidence_ids
            or any(
                not isinstance(item, str) or not item.strip()
                for item in self.source_evidence_ids
            )
        ):
            raise ValueError("source_evidence_ids must contain source IDs")
        allowed = {
            "result_item_limit",
            "per_paper_limit",
            "result_character_budget",
            "result_token_budget",
        }
        if (
            not isinstance(self.reasons, tuple)
            or not self.reasons
            or any(reason not in allowed for reason in self.reasons)
            or len(set(self.reasons)) != len(self.reasons)
        ):
            raise ValueError("reasons must contain unique budget omission reasons")


@dataclass(frozen=True)
class EvidenceBudgetSelection:
    """Selected complete evidence hits and exact counts for the observed pool."""

    hits: tuple[EvidenceHit, ...]
    omissions: tuple[EvidenceBudgetOmission, ...]
    candidate_count: int
    item_limit: int
    per_paper_limit: int
    character_budget: int
    token_budget: int
    characters_used: int
    tokens_used: int
    candidate_pools_truncated: bool

    def __post_init__(self) -> None:
        if not isinstance(self.hits, tuple) or any(
            not isinstance(hit, EvidenceHit) for hit in self.hits
        ):
            raise ValueError("hits must contain EvidenceHit values")
        if not isinstance(self.omissions, tuple) or any(
            not isinstance(item, EvidenceBudgetOmission) for item in self.omissions
        ):
            raise ValueError("omissions must contain EvidenceBudgetOmission values")
        for name in ("candidate_count", "characters_used", "tokens_used"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in (
            "item_limit",
            "per_paper_limit",
            "character_budget",
            "token_budget",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.item_limit > (
            DEFAULT_SEARCH_LIMITS.max_result_limit
            * DEFAULT_SEARCH_LIMITS.max_per_paper_evidence_limit
        ):
            raise ValueError("item_limit exceeds the maximum returned evidence items")
        if self.per_paper_limit > DEFAULT_SEARCH_LIMITS.max_per_paper_evidence_limit:
            raise ValueError("per_paper_limit exceeds the configured maximum")
        if (
            self.character_budget
            > DEFAULT_SEARCH_LIMITS.max_evidence_context_characters
        ):
            raise ValueError("character_budget exceeds the configured maximum")
        if self.token_budget > DEFAULT_SEARCH_LIMITS.max_evidence_context_tokens:
            raise ValueError("token_budget exceeds the configured maximum")
        if self.candidate_count != len(self.hits) + len(self.omissions):
            raise ValueError(
                "candidate_count must account for selected and omitted hits"
            )
        if len(self.hits) > self.item_limit:
            raise ValueError("selected hits exceed item_limit")
        if self.characters_used > self.character_budget:
            raise ValueError("selected hits exceed character_budget")
        if self.tokens_used > self.token_budget:
            raise ValueError("selected hits exceed token_budget")
        chunk_ids = tuple(hit.chunk_id for hit in self.hits) + tuple(
            item.chunk_id for item in self.omissions
        )
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("candidate chunk IDs must be unique")
        ranks = tuple(hit.rank for hit in self.hits) + tuple(
            item.original_rank for item in self.omissions
        )
        if len(set(ranks)) != len(ranks):
            raise ValueError("candidate ranks must be unique")
        paper_counts: dict[str, int] = {}
        for hit in self.hits:
            paper_counts[hit.paper_id] = paper_counts.get(hit.paper_id, 0) + 1
        if any(count > self.per_paper_limit for count in paper_counts.values()):
            raise ValueError("selected hits exceed per_paper_limit")
        if not isinstance(self.candidate_pools_truncated, bool):
            raise ValueError("candidate_pools_truncated must be a boolean")

    @property
    def omitted_count(self) -> int:
        """Number of observed hits omitted by item, per-paper or text budgets."""
        return len(self.omissions)

    @property
    def omitted_count_exact(self) -> bool:
        """Whether the omitted count covers a complete upstream candidate pool."""
        return not self.candidate_pools_truncated

    @property
    def truncated(self) -> bool:
        """Whether any item was omitted or an upstream pool was incomplete."""
        return self.omitted_count > 0 or self.candidate_pools_truncated

    @property
    def warnings(self) -> tuple[str, ...]:
        reasons = {reason for item in self.omissions for reason in item.reasons}
        warnings = []
        if "result_item_limit" in reasons:
            warnings.append("result item limit omitted lower-ranked evidence")
        if "per_paper_limit" in reasons:
            warnings.append("per-paper evidence limit omitted lower-ranked hits")
        if "result_character_budget" in reasons:
            warnings.append("character budget omitted complete evidence units")
        if "result_token_budget" in reasons:
            warnings.append("token budget omitted complete evidence units")
        if self.candidate_pools_truncated:
            warnings.append(
                "candidate pools were truncated; omitted_count covers observed candidates"
            )
        return tuple(warnings)


@dataclass(frozen=True)
class PaperSupportBudgetResult:
    """Paper results after bounding their combined supporting evidence context."""

    papers: tuple[PaperHit, ...]
    selection: EvidenceBudgetSelection

    def __post_init__(self) -> None:
        if not isinstance(self.papers, tuple) or any(
            not isinstance(hit, PaperHit) for hit in self.papers
        ):
            raise ValueError("papers must contain PaperHit values")
        if not isinstance(self.selection, EvidenceBudgetSelection):
            raise ValueError("selection must be EvidenceBudgetSelection")
        paper_supports = tuple(
            evidence.chunk_id
            for paper in self.papers
            for evidence in paper.supporting_evidence
        )
        if set(paper_supports) != {hit.chunk_id for hit in self.selection.hits}:
            raise ValueError("paper supports must match the budget-selected evidence")


def select_evidence_results(
    candidates: Sequence[EvidenceHit],
    *,
    result_limit: int,
    selection_rules: SelectionRules = SelectionRules(),
    candidate_pools_truncated: bool = False,
) -> EvidenceBudgetSelection:
    """Bound an evidence-search page to the request's maximum item count."""
    if (
        isinstance(result_limit, bool)
        or not isinstance(result_limit, int)
        or not 1 <= result_limit <= DEFAULT_SEARCH_LIMITS.max_result_limit
    ):
        raise ValueError(
            "result_limit is outside the configured evidence search bounds"
        )
    return _select_evidence_candidates(
        candidates,
        result_limit=result_limit,
        selection_rules=selection_rules,
        candidate_pools_truncated=candidate_pools_truncated,
        per_paper_limit=selection_rules.evidence_per_paper_limit,
    )


def _select_evidence_candidates(
    candidates: Sequence[EvidenceHit],
    *,
    result_limit: int,
    selection_rules: SelectionRules,
    candidate_pools_truncated: bool,
    per_paper_limit: int,
) -> EvidenceBudgetSelection:
    """Select whole ranked units under item, per-paper, character and token caps.

    Token counts use the profile-bound unicode-token-v1 policy: Unicode word runs
    and individual non-whitespace punctuation marks count as tokens. An item that
    does not fit is omitted whole with its source IDs; selection continues with
    lower-ranked units that may fit the remaining budget. Table hits must already
    carry their source-resolved table context before this function measures them.
    """
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise ValueError("candidates must be a sequence of EvidenceHit values")
    if not isinstance(selection_rules, SelectionRules):
        raise ValueError("selection_rules must be SelectionRules")
    if not isinstance(candidate_pools_truncated, bool):
        raise ValueError("candidate_pools_truncated must be a boolean")
    if (
        isinstance(result_limit, bool)
        or not isinstance(result_limit, int)
        or not 1
        <= result_limit
        <= DEFAULT_SEARCH_LIMITS.max_result_limit
        * DEFAULT_SEARCH_LIMITS.max_per_paper_evidence_limit
    ):
        raise ValueError("result_limit is outside the configured evidence item bounds")
    effective_per_paper_limit = per_paper_limit
    if (
        isinstance(effective_per_paper_limit, bool)
        or not isinstance(effective_per_paper_limit, int)
        or not 1
        <= effective_per_paper_limit
        <= DEFAULT_SEARCH_LIMITS.max_per_paper_evidence_limit
    ):
        raise ValueError("per_paper_limit is outside the configured bounds")

    hits = tuple(candidates)
    if any(not isinstance(hit, EvidenceHit) for hit in hits):
        raise TypeError("candidates must contain EvidenceHit values")
    chunk_ids = tuple(hit.chunk_id for hit in hits)
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("candidates must not repeat chunk IDs")
    ranks = tuple(hit.rank for hit in hits)
    if len(set(ranks)) != len(ranks):
        raise ValueError("candidate ranks must be unique")
    for hit in hits:
        if hit.kind in {"table", "table_row_group"} and hit.table_context is None:
            raise ValueError(
                "table evidence must have source-resolved context before budgeting"
            )

    selected: list[EvidenceHit] = []
    omissions: list[EvidenceBudgetOmission] = []
    selected_by_paper: dict[str, int] = {}
    characters_used = 0
    tokens_used = 0
    rules = selection_rules

    for hit in sorted(hits, key=lambda item: (item.rank, item.chunk_id)):
        item_characters = 0
        item_tokens = 0
        if len(selected) >= result_limit:
            reasons: tuple[EvidenceBudgetReason, ...] = ("result_item_limit",)
        elif selected_by_paper.get(hit.paper_id, 0) >= effective_per_paper_limit:
            reasons = ("per_paper_limit",)
        else:
            item_characters, item_tokens = _text_metrics(hit)
            reason_list: list[EvidenceBudgetReason] = []
            if (
                characters_used + item_characters
                > rules.evidence_result_character_budget
            ):
                reason_list.append("result_character_budget")
            if tokens_used + item_tokens > rules.evidence_result_token_budget:
                reason_list.append("result_token_budget")
            reasons = tuple(reason_list)

        if reasons:
            omissions.append(
                EvidenceBudgetOmission(
                    chunk_id=hit.chunk_id,
                    paper_id=hit.paper_id,
                    original_rank=hit.rank,
                    source_evidence_ids=hit.source_evidence_ids,
                    reasons=reasons,
                )
            )
            continue

        selected.append(hit)
        selected_by_paper[hit.paper_id] = selected_by_paper.get(hit.paper_id, 0) + 1
        characters_used += item_characters
        tokens_used += item_tokens

    return EvidenceBudgetSelection(
        hits=tuple(selected),
        omissions=tuple(omissions),
        candidate_count=len(hits),
        item_limit=result_limit,
        per_paper_limit=effective_per_paper_limit,
        character_budget=rules.evidence_result_character_budget,
        token_budget=rules.evidence_result_token_budget,
        characters_used=characters_used,
        tokens_used=tokens_used,
        candidate_pools_truncated=candidate_pools_truncated,
    )


def apply_evidence_budgets_to_paper_support(
    papers: Sequence[PaperHit],
    *,
    selection_rules: SelectionRules = SelectionRules(),
    candidate_pools_truncated: bool = False,
) -> PaperSupportBudgetResult:
    """Enforce one context budget across supporting hits in a paper-result page.

    The paper rows, paper ranks and paper scores remain unchanged. Supporting evidence
    is chosen in global evidence-rank order, then restored to each paper's original
    support order. Omitted passages keep their source-linked omission records.
    """
    if isinstance(papers, (str, bytes)) or not isinstance(papers, Sequence):
        raise ValueError("papers must be a sequence of PaperHit values")
    if not isinstance(selection_rules, SelectionRules):
        raise ValueError("selection_rules must be SelectionRules")
    if len(papers) > DEFAULT_SEARCH_LIMITS.max_result_limit:
        raise ValueError("papers exceed the configured result item maximum")
    if any(not isinstance(paper, PaperHit) for paper in papers):
        raise TypeError("papers must contain PaperHit values")
    paper_ids = tuple(paper.paper_id for paper in papers)
    if len(set(paper_ids)) != len(paper_ids):
        raise ValueError("paper results must not repeat paper IDs")
    for paper in papers:
        if len(paper.supporting_evidence) > selection_rules.paper_support_limit:
            raise ValueError("paper result exceeds paper_support_limit")

    supports = tuple(
        evidence for paper in papers for evidence in paper.supporting_evidence
    )
    if len(supports) > (
        DEFAULT_SEARCH_LIMITS.max_result_limit
        * DEFAULT_SEARCH_LIMITS.max_per_paper_evidence_limit
    ):
        raise ValueError("paper supports exceed the configured evidence item maximum")
    selection = _select_evidence_candidates(
        supports,
        result_limit=max(1, len(supports)),
        selection_rules=selection_rules,
        candidate_pools_truncated=candidate_pools_truncated,
        per_paper_limit=selection_rules.paper_support_limit,
    )
    selected_ids = {hit.chunk_id for hit in selection.hits}
    updated_papers = tuple(
        replace(
            paper,
            supporting_evidence=tuple(
                hit for hit in paper.supporting_evidence if hit.chunk_id in selected_ids
            ),
        )
        for paper in papers
    )
    return PaperSupportBudgetResult(papers=updated_papers, selection=selection)


def _text_metrics(hit: EvidenceHit) -> tuple[int, int]:
    fragments = [hit.text]
    context = hit.table_context
    if context is not None:
        if context.caption is not None:
            fragments.append(context.caption)
        if context.units is not None:
            fragments.append(context.units)
        fragments.extend(context.footnotes)
        for row in (*context.header_rows, *context.selected_rows):
            for cell in row.cells:
                fragments.extend(_cell_text(cell))
        for cell in context.selected_cells:
            fragments.extend(_cell_text(cell))
    characters = sum(len(fragment) for fragment in fragments)
    tokens = sum(len(_TOKEN_PATTERN.findall(fragment)) for fragment in fragments)
    return characters, tokens


def _cell_text(cell: object) -> tuple[str, ...]:
    return tuple(
        value
        for value in (
            getattr(cell, "value"),
            *getattr(cell, "row_headers"),
            *getattr(cell, "column_headers"),
        )
        if value
    )
