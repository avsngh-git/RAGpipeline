"""Static contract checks for the owner-scoped run views."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).parents[1]
_STATIC = _ROOT / "src/research_platform/api/static"


def test_nav_links_search_new_and_runs() -> None:
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    nav = html.split('<nav id="nav">', maxsplit=1)[1].split("</nav>", maxsplit=1)[0]
    assert 'data-route="search"' in nav
    assert 'data-route="new"' in nav
    assert 'data-route="runs"' in nav
    assert (
        nav.index('data-route="search"')
        < nav.index('data-route="new"')
        < nav.index('data-route="runs"')
    )


def test_run_views_use_the_new_routes() -> None:
    scripts = "\n".join(
        path.read_text(encoding="utf-8") for path in _STATIC.glob("*.js")
    )
    for route in ("/v1/me", "/v1/research", "/record", "/model-calls/", "/cancel"):
        assert route in scripts


def test_run_page_has_report_sections_in_order() -> None:
    source = (_STATIC / "view-run.js").read_text(encoding="utf-8")
    headings = (
        "Claims and their sources",
        "How this answer was made",
        "What verification removed",
        "Diagnosis",
        "Budgets and provenance",
    )
    assert all(heading in source for heading in headings)
    rendered = source[
        source.index("const parts = [") : source.index(
            "content.replaceChildren(...parts.filter(Boolean))"
        )
    ]
    sections = (
        "renderClaims(run.claims, run.papers)",
        'text: "How this answer was made"',
        "renderDrafts(record.drafted_claims)",
        'text: "Diagnosis"',
        "renderBudgets(run, record, state.identity)",
    )
    positions = [rendered.index(section) for section in sections]
    assert positions == sorted(positions)


def test_polling_is_bounded() -> None:
    source = (_STATIC / "view-run.js").read_text(encoding="utf-8")
    assert "setTimeout" in source
    assert "setInterval" not in source
    assert "onLeave(" in source
