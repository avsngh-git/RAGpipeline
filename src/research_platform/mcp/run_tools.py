"""Research-run tool registrations for the MCP server."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Final, Literal
from uuid import UUID

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_platform.runs.contracts import (
    ResearchFilters,
    ResearchMode,
    ResearchRequest,
    ResearchRunView,
    RunStatus,
)
from research_platform.services.errors import AppError
from research_platform.services.text_exposure import (
    external_text_allowed,
    redact_run_view,
)

if TYPE_CHECKING:
    from research_platform.mcp.runtime import McpCall

ACTIVE_POLL_SECONDS: Final = 30
_TERMINAL: Final = frozenset({RunStatus.COMPLETED, RunStatus.FAILED})


class ResearchRunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run: ResearchRunView
    poll_after_seconds: int | None
    note: str


def run_result(view: ResearchRunView, *, text_allowed: bool) -> ResearchRunResult:
    """Map a run view to the MCP result, applying the text exposure policy."""
    if view.status not in _TERMINAL:
        note = "The run is in progress; call get_research_run again after poll_after_seconds."
    elif view.status is RunStatus.COMPLETED:
        note = "The run is complete. Each claim cites evidence by chunk and paper ID."
        if not text_allowed:
            note += " Claim quotes are withheld by this server's policy."
    else:
        note = "The run failed; see failure_category."
        if not text_allowed:
            note += " Claim quotes are withheld by this server's policy."
    return ResearchRunResult(
        run=redact_run_view(view, text_allowed=text_allowed),
        poll_after_seconds=(None if view.status in _TERMINAL else ACTIVE_POLL_SECONDS),
        note=note,
    )


def register_run_tools(server: MCPServer, state: Any) -> None:
    """Register the research-run tools and research-run:// (card P5-12)."""
    if getattr(state, "research_services", None) is None:
        return

    from research_platform.mcp.runtime import run_call

    @server.tool(
        name="start_research_run",
        description="Start a research run: the platform's agent searches the corpus, gathers evidence and writes an answer whose claims cite passages. Runs take several minutes. Returns the queued run; call get_research_run with its run_id after poll_after_seconds until the status is completed or failed.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    async def start_research_run(
        question: Annotated[
            str,
            Field(
                min_length=3,
                max_length=2000,
                description="The research question to answer from the corpus.",
            ),
        ],
        mode: Annotated[
            Literal["quick", "deep_research"],
            Field(
                description="quick runs a fixed search sequence; deep_research lets the agent plan several searches and may take longer."
            ),
        ] = "quick",
        year_from: Annotated[
            int | None,
            Field(
                ge=1900,
                le=2100,
                description="Only evidence from papers published in or after this year.",
            ),
        ] = None,
        year_to: Annotated[
            int | None,
            Field(
                ge=1900,
                le=2100,
                description="Only evidence from papers published in or before this year.",
            ),
        ] = None,
        snapshot_id: Annotated[
            UUID | None,
            Field(description="Corpus snapshot; omit to use the served snapshot."),
        ] = None,
    ) -> ResearchRunResult:
        async def operation(call: McpCall) -> ResearchRunResult:
            call.capabilities.resolve_snapshot(snapshot_id)
            try:
                request = ResearchRequest(
                    question=question,
                    mode=ResearchMode(mode),
                    snapshot_id=snapshot_id,
                    filters=ResearchFilters(year_from=year_from, year_to=year_to),
                )
            except (ValidationError, ValueError):
                raise AppError(
                    "invalid_request", "The research request is invalid.", 422
                ) from None
            view = await call.capabilities.start_run(
                request,
                principal=call.principal,
                request_id=call.request_id,
            )
            return run_result(view, text_allowed=external_text_allowed(call.settings))

        return await run_call(state, "start_research_run", operation)

    @server.tool(
        name="get_research_run",
        description="Read a research run you started: its status, and once completed its answer, claims with their evidence IDs, cited papers and provenance. While it runs, call again after poll_after_seconds.",
        annotations=ToolAnnotations(read_only_hint=True),
        structured_output=True,
    )
    async def get_research_run(
        run_id: Annotated[
            UUID,
            Field(description="The run_id returned by start_research_run."),
        ],
    ) -> ResearchRunResult:
        async def operation(call: McpCall) -> ResearchRunResult:
            view = await call.capabilities.get_run(run_id, principal=call.principal)
            return run_result(view, text_allowed=external_text_allowed(call.settings))

        return await run_call(state, "get_research_run", operation)

    @server.resource(
        "research-run://{run_id}",
        name="research-run",
        description="A research run you started, as JSON.",
        mime_type="application/json",
    )
    async def research_run_resource(run_id: str) -> str:
        async def operation(call: McpCall) -> str:
            try:
                parsed_run_id = UUID(run_id)
            except ValueError:
                raise AppError(
                    "invalid_request", "run_id must be a UUID.", 422
                ) from None
            view = await call.capabilities.get_run(
                parsed_run_id, principal=call.principal
            )
            return run_result(
                view, text_allowed=external_text_allowed(call.settings)
            ).model_dump_json()

        return await run_call(
            state,
            "research_run_resource",
            operation,
            resource=True,
        )
