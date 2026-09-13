"""Exercise the real planner script against a small browser/API harness."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

SCRIPT = (Path(__file__).resolve().parents[1] / "web/static/js/merge-planner.js").read_text(
    encoding="utf-8"
)
HTML = """<!doctype html><html><body>
<section class="merge-shell" data-plan-id="proof">
  <section id="authPanel" hidden><form id="pinForm"><input id="pinInput"></form></section>
  <section id="errorPanel" hidden><p id="errorMessage"></p></section>
  <section id="planner" hidden>
    <span id="planState"><span></span><span></span></span>
    <span id="planTitle"></span><span id="readyCount"></span>
    <span id="itemCount"></span><span id="pendingCount"></span>
    <span id="modeLabel"></span><span id="durationLabel"></span>
    <span id="saveState"></span><p id="subtitleSummary"></p>
    <div id="planNotice"><span></span><span></span></div>
    <button data-sort="input">Input order</button>
    <button data-sort="filename">Filename</button>
    <button data-sort="episode">Episode</button>
    <button data-sort="reverse">Reverse</button>
    <button id="saveOrderButton" hidden>Save current order</button>
    <ol id="mergeList"></ol><div id="emptyState"></div>
  </section>
</section><script src="/static/js/merge-planner.js"></script>
</body></html>"""


def _browser(playwright):
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    kwargs = {"headless": True}
    if os.name == "nt" and edge.is_file():
        kwargs["executable_path"] = str(edge)
    try:
        return playwright.chromium.launch(**kwargs)
    except Exception as error:
        pytest.skip(f"No local Playwright Chromium/Edge browser: {error}")


def test_planner_saves_conflicts_keeps_focus_and_locks():
    playwright_api = pytest.importorskip("playwright.sync_api")
    state = {
        "title": "Proof", "status": "downloading", "mode": "copy",
        "profile_name": "", "duration_seconds": None, "subtitle_summary": "",
        "locked": False, "error": "", "inventory_error": "",
        "ready_count": 0, "pending_count": 0, "enumeration_complete": True,
        "order_revision": 1, "revision": 1,
        "items": [
            {"id": value, "name": name, "original_index": index,
             "ready": False, "placeholder": False}
            for index, (value, name) in enumerate(
                (("a", "First"), ("b", "Second"), ("c", "Third")), 1
            )
        ],
    }
    posts = []

    def serve(route):
        request = route.request
        path = urlsplit(request.url).path
        if path == "/static/js/merge-planner.js":
            route.fulfill(content_type="text/javascript", body=SCRIPT)
        elif path == "/api/merge-plan/proof":
            if request.method == "POST":
                payload = json.loads(request.post_data)
                posts.append((request.url, request.headers, payload))
                if state["locked"] or payload["order_revision"] != state["order_revision"]:
                    route.fulfill(status=409, content_type="application/json",
                                  body=json.dumps({"message": "Order changed", "plan": state}))
                    return
                by_id = {item["id"]: item for item in state["items"]}
                state["items"] = [by_id[item_id] for item_id in payload["order"]]
                state["order_revision"] += 1
            route.fulfill(content_type="application/json", body=json.dumps(state))
        else:
            route.fulfill(content_type="text/html", body=HTML)

    with playwright_api.sync_playwright() as playwright:
        browser = _browser(playwright)
        page = browser.new_page()
        page.route("http://merge.test/**", serve)
        page.goto("http://merge.test/app/merge-plan?gid=merge_proof#pin=abcdefghijkl")
        page.locator("#mergeList li").first.wait_for()
        page.get_by_role("button", name="Reverse").click()
        page.wait_for_function("document.querySelector('#saveState').textContent === 'Up to date'")
        assert [item["id"] for item in state["items"]] == ["c", "b", "a"]
        assert posts[-1][1]["x-merge-plan-pin"] == "abcdefghijkl"
        assert "pin=" not in posts[-1][0]

        focus = page.get_by_role("button", name="Move up: Second")
        focus.focus()
        state["ready_count"] = 1
        page.wait_for_function("document.querySelector('#readyCount').textContent === '1'", timeout=7000)
        assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Move up: Second"

        state["order_revision"] += 1
        page.get_by_role("button", name="Reverse").click()
        page.locator("#saveOrderButton:visible").wait_for()
        page.get_by_role("button", name="Save current order").click()
        page.wait_for_function("document.querySelector('#saveState').textContent === 'Up to date'")
        assert [item["id"] for item in state["items"]] == ["a", "b", "c"]

        state["locked"] = True
        state["status"] = "processing"
        page.wait_for_function("document.querySelector('#planState').dataset.state === 'processing'", timeout=7000)
        assert page.get_by_role("button", name="Reverse").is_disabled()
        browser.close()
