"""Fixtures for browser journeys against isolated in-memory services."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen

import pytest
import uvicorn

pytest.importorskip("playwright")

from playwright.async_api import Browser, Page, async_playwright

from research_platform.api import create_app
from research_platform.api.auth import AuthSettings
from research_platform.auth.keys import InMemoryApiKeyStore, Scope
from research_platform.mcp.testing import fake_state
from research_platform.runs.memory import InMemoryRunStore
from research_platform.services.capabilities import ResearchAPIServices
from research_platform.services.readiness import ReadinessReport
from tests.browser.scripted_runs import ScriptedExecutor


class StubReadinessChecker:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(dependencies={"postgres": True, "qdrant": True})


@dataclass
class UIServer:
    base_url: str
    keys: dict[str, str] = field(repr=False)
    store: InMemoryRunStore
    server_loop: asyncio.AbstractEventLoop
    set_model_available: Callable[[bool], None]
    executor: ScriptedExecutor


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip browser journeys only when the Playwright Chromium binary is absent."""
    browser_cache = Path.home() / ".cache" / "ms-playwright"
    chromium_binaries = (
        *browser_cache.glob("chromium-*/chrome-linux/chrome"),
        *browser_cache.glob("chromium-*/chrome-linux64/chrome"),
        *browser_cache.glob("chromium_headless_shell-*/chrome-linux/headless_shell"),
        *browser_cache.glob("chromium_headless_shell-*/chrome-linux64/headless_shell"),
    )
    if any(path.is_file() for path in chromium_binaries):
        return
    skip = pytest.mark.skip(
        reason="Chromium not installed: run python -m playwright install chromium"
    )
    for item in items:
        if "tests/browser/" in str(item.path):
            item.add_marker(skip)


@pytest.fixture
async def page(anyio_backend: str) -> AsyncIterator[Page]:
    async with async_playwright() as playwright:
        browser: Browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        yield page
        await context.close()
        await browser.close()


@pytest.fixture(scope="session")
def ui_server() -> Iterator[UIServer]:
    state = fake_state()
    settings = state.settings
    store = InMemoryRunStore()
    executor = ScriptedExecutor(store)
    model_state = {"available": True}

    async def llm_available() -> bool:
        return model_state["available"]

    research_services = ResearchAPIServices(
        store=store,
        executor=executor,  # type: ignore[arg-type]
        serving=state.research_services.serving,
        llm_available=llm_available,
    )
    key_store = InMemoryApiKeyStore()
    key_values: dict[str, str] = {}

    async def create_keys() -> None:
        _, key_values["alice"] = await key_store.create(
            "alice", (Scope.READ, Scope.RESEARCH)
        )
        _, key_values["reader"] = await key_store.create("reader", (Scope.READ,))

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, create_keys()).result()
    app = create_app(
        settings=settings,
        dependency_checker=StubReadinessChecker(),
        api_services=state.phase2_services,
        research_services=research_services,
        auth_settings=AuthSettings(mode="api_key", bind_host="127.0.0.1"),
        api_key_store=key_store,
    )

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    config = uvicorn.Config(app, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    loop_holder: list[asyncio.AbstractEventLoop] = []

    def serve() -> None:
        loop = asyncio.new_event_loop()
        loop_holder.append(loop)
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve(sockets=[listener]))
        loop.close()

    thread = threading.Thread(target=serve, name="browser-ui-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15.0
    base_url = f"http://127.0.0.1:{port}"
    while time.monotonic() < deadline:
        if server.started:
            try:
                with urlopen(f"{base_url}/health", timeout=0.5) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                pass
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("The fake UI server did not answer /health.")

    if not loop_holder:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("The fake UI server did not start its event loop.")

    yield UIServer(
        base_url=base_url,
        keys=key_values,
        store=store,
        server_loop=loop_holder[0],
        set_model_available=lambda available: model_state.update(available=available),
        executor=executor,
    )

    server.should_exit = True
    thread.join(timeout=10)
    if thread.is_alive():
        server.force_exit = True
        thread.join(timeout=2)


@pytest.fixture
async def console_errors(anyio_backend: str, page: Page) -> list[str]:
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    return errors
