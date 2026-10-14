"""Serving checks for the small static reviewer UI."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx
from fastapi import FastAPI

from research_platform.api import create_app
from research_platform.api.app import _UI_CONTENT_SECURITY_POLICY
from research_platform.config import Settings
from research_platform.services.readiness import ReadinessReport

_ROOT = Path(__file__).parents[1]
_HTML = _ROOT / "src/research_platform/api/static/index.html"
_SCRIPT = _ROOT / "src/research_platform/api/static/app.js"


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://test:test@localhost:5432/research_test",
        qdrant_url="http://localhost:26333",
    )


def _app() -> FastAPI:
    return create_app(settings=_settings(), dependency_checker=StubReadinessChecker())


async def _request(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_root_serves_the_page_with_a_strict_csp() -> None:
    response = asyncio.run(_request(_app(), "/"))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/ui/app.js" in response.text
    assert response.headers["content-security-policy"] == _UI_CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_script_is_served_as_javascript() -> None:
    response = asyncio.run(_request(_app(), "/ui/app.js"))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_page_has_no_inline_script_or_handlers() -> None:
    html = _HTML.read_text(encoding="utf-8")

    scripts = re.findall(r"<script\b([^>]*)>", html, flags=re.IGNORECASE)
    assert len(scripts) == 1
    assert re.search(r"\bsrc\s*=", scripts[0], flags=re.IGNORECASE)
    assert re.search(r"\son[a-z]+=", html, flags=re.IGNORECASE) is None


def test_script_never_parses_html() -> None:
    script = _SCRIPT.read_text(encoding="utf-8")

    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        assert forbidden not in script


def test_script_calls_only_known_routes() -> None:
    script = _SCRIPT.read_text(encoding="utf-8")
    routes = re.findall(r"[\"'](/v1/[^\"']*)[\"']", script)

    assert routes
    assert set(routes) <= {
        "/v1/serving",
        "/v1/search",
        "/v1/evidence/search",
        "/v1/research/",
    }
    assert any(route.startswith("/v1/research/") for route in routes)


def test_page_makes_no_external_requests() -> None:
    html = _HTML.read_text(encoding="utf-8")
    script = _SCRIPT.read_text(encoding="utf-8")
    external = re.findall(r"https?://[^\"'\s<>]+", html + script)

    assert external == ["https://github.com/avsngh-git/RAGpipeline"]


def test_assets_are_package_data() -> None:
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.setuptools.package-data]" in pyproject
    assert 'research_platform = ["api/static/*.html", "api/static/*.js"]' in pyproject
