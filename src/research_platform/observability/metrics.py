"""Prometheus metrics shared by the API and worker."""

from __future__ import annotations

from typing import Final

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY: Final = CollectorRegistry(auto_describe=True)

_FAST_BUCKETS: Final = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
_LLM_BUCKETS: Final = (
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    1200.0,
    1800.0,
)
_RUN_BUCKETS: Final = (
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    900.0,
    1200.0,
    1800.0,
    3600.0,
)

HTTP_REQUESTS = Counter(
    "research_http_requests_total",
    "HTTP requests by route template and status.",
    ["method", "route", "status"],
    registry=REGISTRY,
)
HTTP_LATENCY = Histogram(
    "research_http_request_duration_seconds",
    "HTTP request duration.",
    ["method", "route"],
    registry=REGISTRY,
)
RUNS_FINISHED = Counter(
    "research_runs_finished_total",
    "Research runs that reached a terminal status.",
    ["mode", "status", "failure_category"],
    registry=REGISTRY,
)
RUN_ACTIVE_SECONDS = Histogram(
    "research_run_active_seconds",
    "Active seconds of finished research runs.",
    ["mode"],
    buckets=_RUN_BUCKETS,
    registry=REGISTRY,
)
RUN_QUEUE_DEPTH = Gauge(
    "research_run_queue_depth",
    "Research runs waiting for the run worker.",
    registry=REGISTRY,
)
TOOL_CALLS = Counter(
    "research_tool_calls_total",
    "Agent tool calls by tool and status.",
    ["tool", "status"],
    registry=REGISTRY,
)
TOOL_LATENCY = Histogram(
    "research_tool_call_duration_seconds",
    "Agent tool call duration.",
    ["tool"],
    buckets=_FAST_BUCKETS,
    registry=REGISTRY,
)
LLM_CALLS = Counter(
    "research_llm_calls_total",
    "Model calls by kind and status.",
    ["kind", "status"],
    registry=REGISTRY,
)
LLM_LATENCY = Histogram(
    "research_llm_call_duration_seconds",
    "Model call duration.",
    ["kind"],
    buckets=_LLM_BUCKETS,
    registry=REGISTRY,
)
LLM_TOKENS = Counter(
    "research_llm_tokens_total",
    "Model tokens by kind and direction.",
    ["kind", "direction"],
    registry=REGISTRY,
)
CLAIM_VERDICTS = Counter(
    "research_claim_verdicts_total",
    "Drafted claims by verification verdict.",
    ["verdict"],
    registry=REGISTRY,
)
SEARCH_STAGE_LATENCY = Histogram(
    "research_search_stage_duration_seconds",
    "Search stage duration.",
    ["stage"],
    buckets=_FAST_BUCKETS,
    registry=REGISTRY,
)
SEARCH_FALLBACKS = Counter(
    "research_search_fallbacks_total",
    "Searches served by a fallback ranking.",
    ["reason"],
    registry=REGISTRY,
)
INGESTION_REQUESTS = Counter(
    "research_ingestion_requests_total",
    "Ingestion requests completed by the worker.",
    ["status"],
    registry=REGISTRY,
)
INGESTION_BACKLOG = Gauge(
    "research_ingestion_backlog",
    "Ingestion requests pending or claimed.",
    registry=REGISTRY,
)
AUTH_FAILURES = Counter(
    "research_auth_failures_total",
    "Rejected API authentication attempts.",
    ["reason"],
    registry=REGISTRY,
)
RATE_LIMITED = Counter(
    "research_rate_limited_total",
    "Requests refused by rate limits.",
    ["route_class"],
    registry=REGISTRY,
)


def render_metrics() -> tuple[bytes, str]:
    """The Prometheus text exposition of REGISTRY and its content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
