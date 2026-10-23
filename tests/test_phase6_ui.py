"""Serving checks for the modular static reviewer UI."""

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
_STATIC = _ROOT / "src/research_platform/api/static"
_HTML = _STATIC / "index.html"


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
    assert '<script type="module" src="/ui/app.js"></script>' in response.text
    assert '<link rel="stylesheet" href="/ui/app.css">' in response.text
    assert response.headers["content-security-policy"] == _UI_CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_every_asset_is_served_with_its_type() -> None:
    app = _app()
    for asset in sorted((*_STATIC.glob("*.js"), *_STATIC.glob("*.css"))):
        response = asyncio.run(_request(app, f"/ui/{asset.name}"))
        expected = "text/javascript" if asset.suffix == ".js" else "text/css"
        assert response.status_code == 200, asset.name
        assert response.headers["content-type"].startswith(expected), asset.name
        assert response.headers["x-content-type-options"] == "nosniff", asset.name


def test_unknown_or_unsafe_asset_names_are_404() -> None:
    app = _app()
    for path in (
        "/ui/missing.js",
        "/ui/APP.JS",
        "/ui/index.html",
        "/ui/..%2Fapp.py",
        "/ui/.hidden.js",
    ):
        assert asyncio.run(_request(app, path)).status_code == 404, path


def test_page_has_no_inline_script_style_or_handlers() -> None:
    html = _HTML.read_text(encoding="utf-8")

    scripts = re.findall(r"<script\b([^>]*)>", html, flags=re.IGNORECASE)
    assert len(scripts) == 1
    assert re.search(r"\bsrc\s*=", scripts[0], flags=re.IGNORECASE)
    assert re.search(r"\btype\s*=\s*['\"]module['\"]", scripts[0], flags=re.IGNORECASE)
    assert re.search(r"<style\b", html, flags=re.IGNORECASE) is None
    assert re.search(r"\son[a-z]+=", html, flags=re.IGNORECASE) is None


def test_scripts_never_parse_html() -> None:
    for script in _STATIC.glob("*.js"):
        text = script.read_text(encoding="utf-8")
        for forbidden in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "document.write",
            "eval(",
            "new Function",
        ):
            assert forbidden not in text, f"{forbidden} in {script.name}"


def test_scripts_import_only_local_modules() -> None:
    for script in _STATIC.glob("*.js"):
        text = script.read_text(encoding="utf-8")
        for imported in re.findall(
            r"\bimport\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", text
        ):
            assert re.fullmatch(r"\./[a-z][a-z0-9-]*\.js", imported), (
                script.name,
                imported,
            )
            assert (_STATIC / imported[2:]).is_file(), (script.name, imported)


def test_scripts_call_only_known_routes() -> None:
    scripts = "\n".join(
        path.read_text(encoding="utf-8") for path in _STATIC.glob("*.js")
    )
    routes = re.findall(r"['\"](/v1/[^'\"]*)['\"]", scripts)

    assert routes
    assert set(routes) <= {
        "/v1/serving",
        "/v1/search",
        "/v1/evidence/search",
        "/v1/papers/",
        "/v1/research",
        "/v1/research/",
        "/v1/me",
    }


def test_page_makes_no_external_requests() -> None:
    static_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            *_STATIC.glob("*.html"),
            *_STATIC.glob("*.js"),
            *_STATIC.glob("*.css"),
        )
    )
    external = re.findall(r"https?://[^\"'\s<>]+", static_text)

    assert external == ["https://github.com/avsngh-git/RAGpipeline"]


def test_assets_are_package_data() -> None:
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.setuptools.package-data]" in pyproject
    assert (
        'research_platform = ["api/static/*.html", "api/static/*.js", "api/static/*.css"]'
        in pyproject
    )
