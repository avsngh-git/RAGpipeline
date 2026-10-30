from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "research_platform" / "api" / "static"


def test_claim_text_is_not_prefixed_with_a_number() -> None:
    source = (STATIC / "view-run.js").read_text()

    assert "`${index + 1}. ${claim.text}`" not in source


def test_dropped_list_has_no_bullets() -> None:
    stylesheet = (STATIC / "app.css").read_text()

    assert ".dropped-list {" in stylesheet
    rule = stylesheet.split(".dropped-list {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    assert "list-style: none" in rule


def test_finding_codes_make_colons_readable() -> None:
    source = (STATIC / "view-run.js").read_text()

    assert 'replaceAll(":", ": ")' in source


def test_header_is_wider_than_the_column() -> None:
    stylesheet = (STATIC / "app.css").read_text()

    assert "header.site .in { max-width: 72rem; }" in stylesheet
    assert "footer.site .in { max-width: 46rem; }" in stylesheet
