"""Application errors that are safe to show to a client."""

from __future__ import annotations

from collections.abc import Mapping


class AppError(Exception):
    """An expected application failure safe to expose to the client."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if not 400 <= status_code <= 599:
            raise ValueError("status_code must be between 400 and 599")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.headers = dict(headers or {})
