"""Typed actions that a research model may propose."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _ActionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class SearchPapersAction(_ActionModel):
    tool: Literal["search_papers"]
    query: str = Field(min_length=1, max_length=500)
    year_from: int | None = Field(None, ge=1900, le=2100)
    year_to: int | None = Field(None, ge=1900, le=2100)
    limit: int = Field(10, ge=1, le=20)

    @model_validator(mode="after")
    def validate_year_range(self) -> SearchPapersAction:
        _validate_year_range(self.year_from, self.year_to)
        return self


class SearchEvidenceAction(_ActionModel):
    tool: Literal["search_evidence"]
    query: str = Field(min_length=1, max_length=500)
    paper_ids: tuple[str, ...] = Field((), max_length=20)
    year_from: int | None = Field(None, ge=1900, le=2100)
    year_to: int | None = Field(None, ge=1900, le=2100)
    limit: int = Field(10, ge=1, le=20)

    @model_validator(mode="after")
    def validate_year_range(self) -> SearchEvidenceAction:
        _validate_year_range(self.year_from, self.year_to)
        return self


class GetPaperAction(_ActionModel):
    tool: Literal["get_paper"]
    paper_id: str = Field(min_length=1, max_length=200)


class GetCitationsAction(_ActionModel):
    tool: Literal["get_citations"]
    paper_id: str = Field(min_length=1, max_length=200)
    limit: int = Field(10, ge=1, le=20)


class GetReferencesAction(_ActionModel):
    tool: Literal["get_references"]
    paper_id: str = Field(min_length=1, max_length=200)
    limit: int = Field(10, ge=1, le=20)


class FindRelatedPapersAction(_ActionModel):
    tool: Literal["find_related_papers"]
    paper_id: str = Field(min_length=1, max_length=200)
    limit: int = Field(10, ge=1, le=20)


Action = Annotated[
    SearchPapersAction
    | SearchEvidenceAction
    | GetPaperAction
    | GetCitationsAction
    | GetReferencesAction
    | FindRelatedPapersAction,
    Field(discriminator="tool"),
]


class ActionBatch(_ActionModel):
    """One to four proposed calls returned by the plan model call."""

    rationale: str = Field(max_length=500)
    actions: tuple[Action, ...] = Field(min_length=1, max_length=4)


class SufficiencyDecision(_ActionModel):
    """Evaluation result and any actions needed to fill evidence gaps."""

    sufficient: bool
    missing: str = Field("", max_length=300)
    next_actions: tuple[Action, ...] = Field((), max_length=4)

    @model_validator(mode="after")
    def validate_next_actions(self) -> SufficiencyDecision:
        if self.sufficient and self.next_actions:
            raise ValueError("sufficient decisions cannot include next_actions")
        return self


def action_key(action: Action) -> str:
    """Return a canonical duplicate-detection key for an action."""
    payload = action.model_dump(mode="json")
    if "query" in payload:
        payload["query"] = payload["query"].strip().lower()
    if "paper_ids" in payload:
        payload["paper_ids"] = sorted(payload["paper_ids"])
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _validate_year_range(year_from: int | None, year_to: int | None) -> None:
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError("year_from must be less than or equal to year_to")
