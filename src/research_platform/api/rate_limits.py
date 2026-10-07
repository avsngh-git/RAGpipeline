"""Per-principal API rate limits."""

from __future__ import annotations

import math
import os
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fastapi import Request

from research_platform.auth.keys import Principal, Scope
from research_platform.observability.metrics import RATE_LIMITED

from .auth import require_scope
from .errors import AppError


class RouteClass(StrEnum):
    RESEARCH_CREATE = "research_create"
    SEARCH = "search"
    PAPER_READ = "paper_read"
    INGEST = "ingest"
    RUN_READ = "run_read"


@dataclass(frozen=True)
class Limit:
    capacity: int
    per_seconds: float


DEFAULT_LIMITS: Final[Mapping[RouteClass, Limit]] = {
    RouteClass.RESEARCH_CREATE: Limit(20, 3600.0),
    RouteClass.SEARCH: Limit(60, 60.0),
    RouteClass.PAPER_READ: Limit(120, 60.0),
    RouteClass.INGEST: Limit(10, 3600.0),
    RouteClass.RUN_READ: Limit(120, 60.0),
}


@dataclass(frozen=True)
class RateLimitSettings:
    limits: Mapping[RouteClass, Limit]
    max_active_runs_per_principal: int = 2
    max_body_bytes: int = 65536

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> RateLimitSettings:
        values = environ if environ is not None else os.environ
        limits: dict[RouteClass, Limit] = {}
        for route_class, default in DEFAULT_LIMITS.items():
            value = values.get(
                f"RESEARCH_PLATFORM_RATE_LIMIT_{route_class.name}",
                f"{default.capacity}/{default.per_seconds:g}",
            )
            try:
                capacity_text, seconds_text = value.split("/")
                capacity = int(capacity_text)
                seconds = float(seconds_text)
            except (ValueError, TypeError) as error:
                raise ValueError(
                    f"RESEARCH_PLATFORM_RATE_LIMIT_{route_class.name} must be capacity/seconds"
                ) from error
            if capacity <= 0 or not math.isfinite(seconds) or seconds <= 0:
                raise ValueError(
                    f"RESEARCH_PLATFORM_RATE_LIMIT_{route_class.name} values must be positive"
                )
            limits[route_class] = Limit(capacity, seconds)

        def positive_int(name: str, default: int) -> int:
            try:
                value = int(values.get(name, str(default)))
            except ValueError as error:
                raise ValueError(f"{name} must be a positive integer") from error
            if value <= 0:
                raise ValueError(f"{name} must be a positive integer")
            return value

        return cls(
            limits=limits,
            max_active_runs_per_principal=positive_int(
                "RESEARCH_PLATFORM_MAX_ACTIVE_RUNS_PER_KEY", 2
            ),
            max_body_bytes=positive_int("RESEARCH_PLATFORM_MAX_BODY_BYTES", 65536),
        )


class TokenBucketLimiter:
    """Bounded token buckets keyed by principal and route class."""

    def __init__(
        self,
        settings: RateLimitSettings,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_buckets: int = 10000,
    ) -> None:
        if max_buckets <= 0:
            raise ValueError("max_buckets must be positive")
        self._settings = settings
        self._clock = clock
        self._max_buckets = max_buckets
        self._buckets: OrderedDict[tuple[str, RouteClass], tuple[float, float]] = (
            OrderedDict()
        )

    def check(self, principal: str, route_class: RouteClass) -> float | None:
        limit = self._settings.limits[route_class]
        now = self._clock()
        key = (principal, route_class)
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_buckets:
                self._buckets.popitem(last=False)
            tokens, updated_at = float(limit.capacity), now
        else:
            tokens, updated_at = bucket
            tokens = min(
                float(limit.capacity),
                tokens
                + max(0.0, now - updated_at) * limit.capacity / limit.per_seconds,
            )
        if tokens < 1.0:
            retry_after = (1.0 - tokens) * limit.per_seconds / limit.capacity
            self._buckets[key] = (tokens, now)
            return retry_after
        self._buckets[key] = (tokens - 1.0, now)
        return None


def rate_limited(
    scope: Scope, route_class: RouteClass
) -> Callable[[Request], Awaitable[Principal]]:
    """Authenticate and consume one token for a route class."""
    authenticate = require_scope(scope)

    async def dependency(request: Request) -> Principal:
        principal = await authenticate(request)
        retry_after = request.app.state.rate_limiter.check(principal.name, route_class)
        if retry_after is not None:
            RATE_LIMITED.labels(route_class.value).inc()
            raise AppError(
                "rate_limited",
                "Too many requests; retry later.",
                429,
                headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
            )
        return principal

    return dependency
