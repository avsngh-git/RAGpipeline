"""Real-browser journeys through the research UI using only local fakes."""

from __future__ import annotations

import asyncio
import re

import pytest
from playwright.async_api import Page, expect

from tests.browser.conftest import UIServer
from tests.browser.scripted_runs import seed_completed_run

pytestmark = [pytest.mark.browser, pytest.mark.anyio]


async def _connect(page: Page, ui_server: UIServer, key_name: str = "alice") -> None:
    await page.goto(f"{ui_server.base_url}/")
    await page.locator("#api-key").fill(ui_server.keys[key_name])
    await page.locator("#api-key").press("Enter")
    await expect(page.locator("#who")).to_contain_text("generation")


async def _papers_search(page: Page) -> None:
    await page.get_by_role("button", name="Papers").click()
    await page.locator("#q").fill("Retrieval")
    await page.get_by_role("button", name="Search").click()
    await expect(page.get_by_role("link", name="Retrieval paper A")).to_be_visible()


def _seed_completed(ui_server: UIServer) -> str:
    future = asyncio.run_coroutine_threadsafe(
        seed_completed_run(ui_server.store, "alice"), ui_server.server_loop
    )
    return str(future.result(timeout=5))


async def test_key_prompt_then_paper_and_evidence_search(
    page: Page, ui_server: UIServer
) -> None:
    await _connect(page, ui_server)
    await _papers_search(page)

    await page.get_by_role("button", name="Evidence").click()
    await page.locator("#q").fill("hybrid")
    await page.get_by_role("button", name="Search").click()
    await expect(page.get_by_text("Hybrid retrieval improves recall.")).to_be_visible()
    text_checkbox = page.locator("label").filter(has_text="Text").locator("input")
    await expect(text_checkbox).to_be_checked()
    await text_checkbox.uncheck()
    async with page.expect_request(
        lambda request: request.url.endswith("/v1/evidence/search")
    ) as request_info:
        await page.get_by_role("button", name="Search").click()
    request = await request_info.value
    request_body = request.post_data_json
    assert request_body is not None
    assert "text" not in request_body["filters"]["evidence_kinds"]


async def test_paper_page_from_a_hit(page: Page, ui_server: UIServer) -> None:
    await _connect(page, ui_server)
    await _papers_search(page)
    await page.get_by_role("link", name="Retrieval paper A").click()
    await expect(page).to_have_url(re.compile(r"#/papers/W[0-9]+$"))
    await expect(
        page.get_by_role("heading", name="Retrieval paper A", level=1)
    ).to_be_visible()
    await expect(page.get_by_role("heading", name="References")).to_be_visible()
    await expect(
        page.get_by_role("heading", name="Cited by, in this collection")
    ).to_be_visible()


async def test_start_run_and_watch_it_complete(page: Page, ui_server: UIServer) -> None:
    ui_server.executor.step_seconds = 1.1
    await _connect(page, ui_server)
    await page.goto(f"{ui_server.base_url}/#/new")
    await page.locator("#run-question").fill("zq7731 browser journey question")
    await page.locator("#start-run").click()
    await expect(page).to_have_url(re.compile(r"#/runs/[0-9a-f-]{36}$"), timeout=5000)
    await expect(
        page.get_by_text(re.compile(r"running", re.IGNORECASE))
    ).to_be_visible()
    await expect(page.get_by_text("Called search_papers")).to_be_visible(timeout=5000)
    await expect(
        page.get_by_role("heading", name="Claims and their sources")
    ).to_be_visible(timeout=12000)
    await expect(page.locator("blockquote")).to_contain_text("zq7731")
    answer_call = (
        page.locator("li.model").filter(has_text="Wrote the answer").locator("details")
    )
    await answer_call.get_by_text("Prompt, thinking and output").click()
    await expect(
        answer_call.get_by_text(re.compile("^system$", re.IGNORECASE))
    ).to_be_visible()


async def test_verification_removed_section(page: Page, ui_server: UIServer) -> None:
    run_id = _seed_completed(ui_server)
    await _connect(page, ui_server)
    await page.goto(f"{ui_server.base_url}/#/runs/{run_id}")
    section = page.get_by_role("heading", name="What verification removed")
    await expect(section).to_be_visible()
    await expect(page.get_by_text("zq7731 unsupported drafted claim.")).to_be_visible()
    await expect(page.get_by_text("It failed quote verification:")).to_be_visible()


async def test_model_text_not_recorded_message(page: Page, ui_server: UIServer) -> None:
    run_id = _seed_completed(ui_server)
    await _connect(page, ui_server)
    await page.goto(f"{ui_server.base_url}/#/runs/{run_id}")
    call = (
        page.locator("li.model")
        .filter(has_text="Judged whether the evidence was enough")
        .locator("details")
    )
    await call.get_by_text("Prompt, thinking and output").click()
    await expect(call.get_by_text("Model text was not recorded")).to_be_visible()


async def test_cancel_a_running_run(page: Page, ui_server: UIServer) -> None:
    ui_server.executor.step_seconds = 5.0
    await _connect(page, ui_server)
    await page.goto(f"{ui_server.base_url}/#/new")
    await page.locator("#run-question").fill("zq7731 cancellation journey")
    await page.locator("#start-run").click()
    await expect(page).to_have_url(re.compile(r"#/runs/([0-9a-f-]{36})$"), timeout=5000)
    run_id = page.url.rsplit("/", 1)[1]
    await page.get_by_role("button", name="Cancel run").click()
    await page.get_by_role("button", name="Cancel run").last.click()
    await expect(page.get_by_text("cancelled", exact=True)).to_be_visible(timeout=5000)
    response = await page.request.get(
        f"{ui_server.base_url}/v1/research/{run_id}",
        headers={"Authorization": f"Bearer {ui_server.keys['alice']}"},
    )
    assert response.status == 200
    body = await response.json()
    assert body["failure_category"] == "cancelled_by_principal"


async def test_run_form_disabled_without_model(page: Page, ui_server: UIServer) -> None:
    ui_server.set_model_available(False)
    try:
        await _connect(page, ui_server)
        await page.goto(f"{ui_server.base_url}/#/new")
        await expect(page.locator("#start-run")).to_be_disabled()
        await expect(
            page.get_by_text("Research runs need the local model")
        ).to_be_visible()
    finally:
        ui_server.set_model_available(True)


async def test_read_only_key_cannot_start_runs(page: Page, ui_server: UIServer) -> None:
    await _connect(page, ui_server, "reader")
    await page.goto(f"{ui_server.base_url}/#/new")
    await expect(page.locator("#start-run")).to_be_disabled()
    await expect(page.get_by_text("cannot start them")).to_be_visible()


async def test_runs_list_links_to_runs(page: Page, ui_server: UIServer) -> None:
    run_id = _seed_completed(ui_server)
    await _connect(page, ui_server)
    await page.goto(f"{ui_server.base_url}/#/runs")
    await page.locator(f'a[href="#/runs/{run_id}"]').click()
    await expect(page).to_have_url(f"{ui_server.base_url}/#/runs/{run_id}")
    await expect(
        page.get_by_role("heading", name="zq7731 seeded research question", level=1)
    ).to_be_visible()


async def test_old_run_links_still_work(page: Page, ui_server: UIServer) -> None:
    run_id = _seed_completed(ui_server)
    await _connect(page, ui_server)
    await page.goto(f"{ui_server.base_url}/#run={run_id}")
    await expect(page).to_have_url(f"{ui_server.base_url}/#/runs/{run_id}")
    await expect(
        page.get_by_role("heading", name="zq7731 seeded research question")
    ).to_be_visible()


async def test_phone_width_has_no_sideways_scroll(
    page: Page, ui_server: UIServer
) -> None:
    run_id = _seed_completed(ui_server)
    await _connect(page, ui_server)
    await page.set_viewport_size({"width": 400, "height": 800})
    await page.goto(f"{ui_server.base_url}/#/search")
    await expect(
        page.get_by_role("heading", name="Search the collection")
    ).to_be_visible()
    assert await page.evaluate("document.scrollingElement.scrollWidth") <= 400
    await page.goto(f"{ui_server.base_url}/#/runs/{run_id}")
    await expect(
        page.get_by_role("heading", name="zq7731 seeded research question")
    ).to_be_visible()
    assert await page.evaluate("document.scrollingElement.scrollWidth") <= 400


async def test_no_console_errors(
    page: Page, ui_server: UIServer, console_errors: list[str]
) -> None:
    run_id = _seed_completed(ui_server)
    await _connect(page, ui_server)
    await _papers_search(page)
    await page.get_by_role("link", name="Retrieval paper A").click()
    await expect(page.get_by_role("heading", name="References")).to_be_visible()
    await page.goto(f"{ui_server.base_url}/#/runs/{run_id}")
    await expect(
        page.get_by_role("heading", name="Claims and their sources")
    ).to_be_visible()
    assert console_errors == []
