"""Static checks for the P6-34 cold-review UI corrections."""

from __future__ import annotations

from pathlib import Path

_STATIC = Path("src/research_platform/api/static")


def test_run_view_explains_failed_checks_and_diagnosis_labels() -> None:
    source = (_STATIC / "view-run.js").read_text(encoding="utf-8")

    for name in (
        "quote_found",
        "words_from_quote",
        "numbers_from_quote",
        "intensifiers_from_quote",
        "no_handles_in_text",
        "quote_names_its_row",
        "no_other_row_named",
    ):
        assert f"{name}:" in source
    assert 'drafts_rejected: "Drafted claims by verdict"' in source


def test_new_run_notice_explains_gpu_requirement() -> None:
    source = (_STATIC / "view-new-run.js").read_text(encoding="utf-8")

    assert "NVIDIA GPU" in source


def test_key_page_says_where_the_key_was_saved() -> None:
    source = (_STATIC / "view-key.js").read_text(encoding="utf-8")

    assert "demo-data/api-key" in source
    assert "printed" not in source


def test_unknown_paper_has_a_clear_not_found_state() -> None:
    source = (_STATIC / "view-paper.js").read_text(encoding="utf-8")

    assert 'text: "Paper not found"' in source
    assert 'href: "#/search"' in source
    assert "text: `This server has no record of ${paperId}.`" in source


def test_duplicate_paper_evidence_and_empty_run_list_are_simplified() -> None:
    search_source = (_STATIC / "view-search.js").read_text(encoding="utf-8")
    runs_source = (_STATIC / "view-runs.js").read_text(encoding="utf-8")

    assert "value.trim().toLowerCase() === title.trim().toLowerCase()" in search_source
    assert "tableWrap.hidden = !hasRuns" in runs_source
    assert "header.hidden" not in runs_source


def test_paper_graph_endpoints_explain_missing_membership_and_metadata() -> None:
    source = (_STATIC / "view-paper.js").read_text(encoding="utf-8")

    assert "— not in this collection" in source
    assert "— not in this collection, no metadata" in source
