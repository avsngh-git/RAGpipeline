from __future__ import annotations

import re
from datetime import date

import pytest

_ENTRY_PATTERN = re.compile(
    r"^(CVE-\d{4}-\d{4,}|GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4})"
    r"\s+#\s*reason:\s*\S.*;\s*expires:\s*(\d{4}-\d{2}-\d{2})$"
)


def _validate_trivyignore(content: str, today: date | None = None) -> None:
    current_date = today or date.today()
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line or line.startswith("#"):
            continue

        match = _ENTRY_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError(
                f"line {line_number} must include a finding ID, reason, and expiry"
            )

        try:
            expiry = date.fromisoformat(match.group(2))
        except ValueError as error:
            raise ValueError(
                f"line {line_number} has an invalid expiry date"
            ) from error
        if expiry < current_date:
            raise ValueError(f"line {line_number} has an expired exception")


def test_trivyignore_entries_have_reasons_and_current_expiry() -> None:
    _validate_trivyignore(open(".trivyignore", encoding="utf-8").read())


def test_parser_accepts_valid_entry() -> None:
    _validate_trivyignore(
        "CVE-2026-12345 # reason: awaiting upstream release; expires: 2026-12-31",
        today=date(2026, 10, 6),
    )


def test_parser_rejects_missing_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        _validate_trivyignore(
            "CVE-2026-12345 # expires: 2026-12-31",
            today=date(2026, 10, 6),
        )


def test_parser_rejects_expired_entry() -> None:
    with pytest.raises(ValueError, match="expired"):
        _validate_trivyignore(
            "GHSA-aaaa-bbbb-cccc # reason: awaiting upstream release; expires: 2026-10-05",
            today=date(2026, 10, 6),
        )


def test_parser_rejects_invalid_calendar_date() -> None:
    with pytest.raises(ValueError, match="invalid expiry"):
        _validate_trivyignore(
            "CVE-2026-12345 # reason: awaiting upstream release; expires: 2026-02-30",
            today=date(2026, 1, 1),
        )


def test_parser_rejects_surrounding_whitespace() -> None:
    with pytest.raises(ValueError, match="finding ID"):
        _validate_trivyignore(
            " CVE-2026-12345 # reason: awaiting upstream release; expires: 2026-12-31 ",
            today=date(2026, 10, 6),
        )


def test_parser_rejects_indented_comment() -> None:
    with pytest.raises(ValueError, match="finding ID"):
        _validate_trivyignore(" # this is not a comment", today=date(2026, 10, 6))
