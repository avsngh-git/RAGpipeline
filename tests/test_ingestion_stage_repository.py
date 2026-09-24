"""Tests for safe persistence of ingestion failure summaries."""

import pytest

from research_platform.ingestion.runner import (
    DocumentStageFailure,
    IngestionExecutionError,
    SharedPipelineFailure,
)
from research_platform.ingestion.stage_repository import _safe_error_message


def test_error_summary_omits_credentials_and_untrusted_document_text() -> None:
    excerpt = "RESTRICTED_PAPER_PASSAGE_9f14"
    message = (
        f"parser failed on passage {excerpt}; Authorization: Bearer bearer-secret; "
        "API_KEY=api-secret; postgresql://research:db-secret@localhost:5432/research"
    )

    sanitized = _safe_error_message(message)

    assert sanitized == "details omitted; see failure_category"
    for sensitive_value in (
        excerpt,
        "bearer-secret",
        "api-secret",
        "db-secret",
    ):
        assert sensitive_value not in sanitized


def test_error_summary_is_bounded_independently_of_exception_text() -> None:
    sanitized = _safe_error_message("parser failed: " + "x" * 2000)

    assert sanitized == "details omitted; see failure_category"
    assert len(sanitized) < 1000


def test_document_failure_category_must_be_a_machine_readable_token() -> None:
    failure = DocumentStageFailure("parse-failed", "details include paper text")
    assert failure.category == "parse-failed"

    with pytest.raises(ValueError, match="machine-readable category"):
        DocumentStageFailure("paper passage: RESTRICTED TEXT", "parse failed")


@pytest.mark.parametrize("failure_type", [DocumentStageFailure, SharedPipelineFailure])
def test_stage_failure_retryable_flag_must_be_boolean(failure_type) -> None:
    with pytest.raises(ValueError, match="boolean retryable flag"):
        failure_type("parser_failed", "failure details", retryable="yes")


def test_execution_error_retryable_flag_must_be_boolean() -> None:
    with pytest.raises(ValueError, match="retryable flag must be a boolean"):
        IngestionExecutionError("runtime_error", retryable=1)
