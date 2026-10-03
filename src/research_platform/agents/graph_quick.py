"""Fixed search-and-answer graph for quick research runs."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from research_platform.agents.actions import SearchEvidenceAction, SearchPapersAction
from research_platform.agents.nodes import (
    NodeDependencies,
    ToolStepFailed,
    _run_action,
    answer_node,
)
from research_platform.agents.state import ResearchState


def build_quick_graph(
    deps: NodeDependencies,
) -> StateGraph[ResearchState, None, ResearchState, ResearchState]:
    """Build the bounded three-step quick workflow."""

    async def search_papers(state: ResearchState) -> dict[str, object]:
        update, observation = await _run_action(
            deps,
            state,
            SearchPapersAction(
                tool="search_papers",
                query=state["question"][:500],
                year_from=deps.context.filters.year_from,
                year_to=deps.context.filters.year_to,
                limit=10,
            ),
        )
        if observation.status == "failed":
            raise ToolStepFailed(observation.error_category or "internal")
        papers = observation.summary.get("papers", [])
        paper_ids = (
            [
                paper["paper_id"]
                for paper in papers[:5]
                if isinstance(paper, dict) and isinstance(paper.get("paper_id"), str)
            ]
            if isinstance(papers, list)
            else []
        )
        return {**update, "candidate_paper_ids": paper_ids}

    async def search_evidence(state: ResearchState) -> dict[str, object]:
        update, observation = await _run_action(
            deps,
            state,
            SearchEvidenceAction(
                tool="search_evidence",
                query=state["question"][:500],
                paper_ids=tuple(state["candidate_paper_ids"]),
                year_from=None,
                year_to=None,
                limit=20,
            ),
        )
        if observation.status == "failed":
            raise ToolStepFailed(observation.error_category or "internal")
        return update

    async def answer(state: ResearchState) -> dict[str, object]:
        return await answer_node(deps, state)

    builder = StateGraph(ResearchState)
    builder.add_node("search_papers", search_papers)
    builder.add_node("search_evidence", search_evidence)
    builder.add_node("answer", answer)
    builder.add_edge(START, "search_papers")
    builder.add_edge("search_papers", "search_evidence")
    builder.add_edge("search_evidence", "answer")
    builder.add_edge("answer", END)
    return builder
