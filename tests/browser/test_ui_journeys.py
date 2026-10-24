"""Real-browser journeys through the research UI using only local fakes."""

from __future__ import annotations

import asyncio
import re

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import UIServer
from tests.browser.scripted_runs import seed_completed_run

pytestmark = pytest.mark.browser


def _connect(page: Page, ui_server: UIServer, key_name: str = "alice") -> None:
    page.goto(f"{ui_server.base_url}/")
    page.locator("#api-key").fill(ui_server.keys[key_name])
    page.locator("#api-key").press("Enter")
    expect(page.locator("#who")).to_contain_text("generation")


def _papers_search(page: Page) -> None:
    page.get_by_role("button", name="Papers").click()
    page.locator("#q").fill("Retrieval")
    page.get_by_role("button", name="Search").click()
    expect(page.get_by_role("link", name="Retrieval paper A")).to_be_visible()


def _seed_completed(ui_server: UIServer) -> str:
    future = asyncio.run_coroutine_threadsafe(
        seed_completed_run(ui_server.store, "alice"), ui_server.server_loop
    )
    return str(future.result(timeout=5))


def test_key_prompt_then_paper_and_evidence_search(
    page: Page, ui_server: UIServer
) -> None:
    _connect(page, ui_server)
    _papers_search(page)

    page.get_by_role("button", name="Evidence").click()
    page.locator("#q").fill("hybrid")
    page.get_by_role("button", name="Search").click()
    expect(page.get_by_text("Hybrid retrieval improves recall.")).to_be_visible()
    text_checkbox = page.locator("label").filter(has_text="Text").locator("input")
    expect(text_checkbox).to_be_checked()
    text_checkbox.uncheck()
    with page.expect_request(
        lambda request: request.url.endswith("/v1/evidence/search")
    ) as request_info:
        page.get_by_role("button", name="Search").click()
    request_body = request_info.value.post_data_json
    assert "text" not in request_body["filters"]["evidence_kinds"]


def test_paper_page_from_a_hit(page: Page, ui_server: UIServer) -> None:
    _connect(page, ui_server)
    _papers_search(page)
    page.get_by_role("link", name="Retrieval paper A").click()
    expect(page).to_have_url(re.compile(r"#/papers/W[0-9]+$"))
    expect(
        page.get_by_role("heading", name="Retrieval paper A", level=1)
    ).to_be_visible()
    expect(page.get_by_role("heading", name="References")).to_be_visible()
    expect(
        page.get_by_role("heading", name="Cited by, in this collection")
    ).to_be_visible()


def test_start_run_and_watch_it_complete(page: Page, ui_server: UIServer) -> None:
    ui_server.executor.step_seconds = 1.1
    _connect(page, ui_server)
    page.goto(f"{ui_server.base_url}/#/new")
    page.locator("#run-question").fill("zq7731 browser journey question")
    page.locator("#start-run").click()
    expect(page).to_have_url(re.compile(r"#/runs/[0-9a-f-]{36}$"), timeout=5000)
    expect(page.get_by_text(re.compile(r"running", re.IGNORECASE))).to_be_visible()
    expect(page.get_by_text("Called search_papers")).to_be_visible(timeout=5000)
    expect(page.get_by_role("heading", name="Claims and their sources")).to_be_visible(
        timeout=12000
    )
    expect(page.locator("blockquote")).to_contain_text("zq7731")
    answer_call = (
        page.locator("li.model").filter(has_text="Wrote the answer").locator("details")
    )
    answer_call.get_by_text("Prompt, thinking and output").click()
    expect(
        answer_call.get_by_text(re.compile("^system$", re.IGNORECASE))
    ).to_be_visible()


def test_verification_removed_section(page: Page, ui_server: UIServer) -> None:
    run_id = _seed_completed(ui_server)
    _connect(page, ui_server)
    page.goto(f"{ui_server.base_url}/#/runs/{run_id}")
    section = page.get_by_role("heading", name="What verification removed")
    expect(section).to_be_visible()
    expect(page.get_by_text("zq7731 unsupported drafted claim.")).to_be_visible()
    expect(page.get_by_text("It failed quote verification:")).to_be_visible()


def test_model_text_not_recorded_message(page: Page, ui_server: UIServer) -> None:
    run_id = _seed_completed(ui_server)
    _connect(page, ui_server)
    page.goto(f"{ui_server.base_url}/#/runs/{run_id}")
    call = (
        page.locator("li.model")
        .filter(has_text="Judged whether the evidence was enough")
        .locator("details")
    )
    call.get_by_text("Prompt, thinking and output").click()
    expect(call.get_by_text("Model text was not recorded")).to_be_visible()


def test_cancel_a_running_run(page: Page, ui_server: UIServer) -> None:
    ui_server.executor.step_seconds = 5.0
    _connect(page, ui_server)
    page.goto(f"{ui_server.base_url}/#/new")
    page.locator("#run-question").fill("zq7731 cancellation journey")
    page.locator("#start-run").click()
    expect(page).to_have_url(re.compile(r"#/runs/([0-9a-f-]{36})$"), timeout=5000)
    run_id = page.url.rsplit("/", 1)[1]
    page.get_by_role("button", name="Cancel run").click()
    page.get_by_role("button", name="Cancel run").last.click()
    expect(page.get_by_text("cancelled", exact=True)).to_be_visible(timeout=5000)
    response = page.request.get(
        f"{ui_server.base_url}/v1/research/{run_id}",
        headers={"Authorization": f"Bearer {ui_server.keys['alice']}"},
    )
    assert response.status == 200
    assert response.json()["failure_category"] == "cancelled_by_principal"


def test_run_form_disabled_without_model(page: Page, ui_server: UIServer) -> None:
    ui_server.set_model_available(False)
    try:
        _connect(page, ui_server)
        page.goto(f"{ui_server.base_url}/#/new")
        expect(page.locator("#start-run")).to_be_disabled()
        expect(page.get_by_text("Research runs need the local model")).to_be_visible()
    finally:
        ui_server.set_model_available(True)


def test_read_only_key_cannot_start_runs(page: Page, ui_server: UIServer) -> None:
    _connect(page, ui_server, "reader")
    page.goto(f"{ui_server.base_url}/#/new")
    expect(page.locator("#start-run")).to_be_disabled()
    expect(page.get_by_text("cannot start them")).to_be_visible()


def test_runs_list_links_to_runs(page: Page, ui_server: UIServer) -> None:
    run_id = _seed_completed(ui_server)
    _connect(page, ui_server)
    page.goto(f"{ui_server.base_url}/#/runs")
    page.locator(f'a[href="#/runs/{run_id}"]').click()
    expect(page).to_have_url(f"{ui_server.base_url}/#/runs/{run_id}")
    expect(
        page.get_by_role("heading", name="zq7731 seeded research question", level=1)
    ).to_be_visible()


def test_old_run_links_still_work(page: Page, ui_server: UIServer) -> None:
    run_id = _seed_completed(ui_server)
    _connect(page, ui_server)
    page.goto(f"{ui_server.base_url}/#run={run_id}")
    expect(page).to_have_url(f"{ui_server.base_url}/#/runs/{run_id}")
    expect(
        page.get_by_role("heading", name="zq7731 seeded research question")
    ).to_be_visible()


def test_phone_width_has_no_sideways_scroll(page: Page, ui_server: UIServer) -> None:
    run_id = _seed_completed(ui_server)
    _connect(page, ui_server)
    page.set_viewport_size({"width": 400, "height": 800})
    page.goto(f"{ui_server.base_url}/#/search")
    expect(page.get_by_role("heading", name="Search the collection")).to_be_visible()
    assert page.evaluate("document.scrollingElement.scrollWidth") <= 400
    page.goto(f"{ui_server.base_url}/#/runs/{run_id}")
    expect(
        page.get_by_role("heading", name="zq7731 seeded research question")
    ).to_be_visible()
    assert page.evaluate("document.scrollingElement.scrollWidth") <= 400


def test_no_console_errors(
    page: Page, ui_server: UIServer, console_errors: list[str]
) -> None:
    run_id = _seed_completed(ui_server)
    _connect(page, ui_server)
    _papers_search(page)
    page.get_by_role("link", name="Retrieval paper A").click()
    expect(page.get_by_role("heading", name="References")).to_be_visible()
    page.goto(f"{ui_server.base_url}/#/runs/{run_id}")
    expect(page.get_by_role("heading", name="Claims and their sources")).to_be_visible()
    assert console_errors == []
