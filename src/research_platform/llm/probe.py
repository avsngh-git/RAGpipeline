"""Cached health probe for the configured Ollama model."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx


class OllamaProbe:
    """Cached check that Ollama answers and has the configured model."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        model: str,
        ttl_seconds: float = 15.0,
        timeout_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._model = model
        self._expected_names = {model}
        if ":" not in model:
            self._expected_names.add(f"{model}:latest")
        self._ttl_seconds = ttl_seconds
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._cached_at: float | None = None
        self._cached_result = False

    async def __call__(self) -> bool:
        now = self._clock()
        if self._cached_at is not None and now - self._cached_at < self._ttl_seconds:
            return self._cached_result
        try:
            response = await self._http.get("/api/tags", timeout=self._timeout_seconds)
            payload: Any = response.json()
            models = payload.get("models") if isinstance(payload, dict) else None
            available = (
                response.status_code == 200
                and isinstance(models, list)
                and any(
                    isinstance(item, dict)
                    and any(
                        item.get(key) in self._expected_names
                        for key in ("name", "model")
                    )
                    for item in models
                )
            )
        except (httpx.HTTPError, ValueError, TypeError):
            available = False
        self._cached_at = now
        self._cached_result = available
        return available
