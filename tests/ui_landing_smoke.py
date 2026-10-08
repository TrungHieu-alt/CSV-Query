"""Chrome checks for the isolated landing page and its scroll handoff.

Run: .venv/Scripts/python.exe -B tests/ui_landing_smoke.py
"""
from __future__ import annotations

import functools
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright
import uvicorn

from backend.app.config import Settings
from backend.app.main import create_app
from ui_smoke import FixtureLLM, LocalHTTPServer, SimpleHTTPRequestHandler, ask


def main():
    artifacts = Path(tempfile.mkdtemp(prefix="studio-landing-ui-"))
    checks = []
    app = create_app(Settings(
        gemini_api_key="fixture", gemini_backup_api_key="",
        csv_path=ROOT / "backend/data/sales_data.csv", rate_limit_per_minute=100,
        allowed_origins=["http://127.0.0.1:18900"],
    ), llm_client=FixtureLLM())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=18901, log_level="error"))
    api_thread = threading.Thread(target=server.run, daemon=True)
    api_thread.start()
    static = LocalHTTPServer(("127.0.0.1", 18900), functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT / "frontend")))
    static_thread = threading.Thread(target=static.serve_forever, daemon=True)
    static_thread.start()

    def passed(name):
        checks.append(name)
        print("PASS:", name, flush=True)

    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)

            def context(**options):
                result = browser.new_context(**options)
                result.route("**/config.js*", lambda route: route.fulfill(content_type="application/javascript", body='window.APP_CONFIG = { API_BASE_URL: "http://127.0.0.1:18901" };'))
                return result

            desktop = context(viewport={"width": 1366, "height": 768})
            page = desktop.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto("http://127.0.0.1:18900/landing/")
            page.evaluate("document.fonts.ready")
            expect(page.get_by_role("heading", level=1)).to_contain_text("More perspective.")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(artifacts / "desktop.png"))
            passed("Desktop landing, independent document and assets, no horizontal overflow")

            page.get_by_role("button", name="View as table").click()
            expect(page.locator("#table-demo")).to_be_visible()
            expect(page.locator("#table-demo tbody tr")).to_have_count(4)
            page.get_by_role("button", name="View as chart").click()
            expect(page.locator("#chart-demo")).to_be_visible()
            page.get_by_role("button", name="How it works", exact=True).click()
            expect(page.locator("#how-dialog")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.locator("#how-dialog")).to_be_hidden()
            page.get_by_role("button", name="Good to know", exact=True).first.click()
            expect(page.locator("#faq-dialog")).to_be_visible()
            page.get_by_text("Will my uploads stay here?", exact=True).click()
            expect(page.locator("#faq-dialog")).to_contain_text("backend’s memory")
            page.locator("#faq-dialog").get_by_role("button", name="Close", exact=True).click()
            passed("Interactive chart/table sample, dialogs, FAQ and Escape dismissal")

            page.evaluate("window.scrollTo(0, Math.max(0, document.querySelector('#landing-sheet').offsetHeight - innerHeight) + Math.max(420, innerHeight * .9) * .5)")
            page.wait_for_function("parseFloat(document.querySelector('#landing-sheet').style.opacity) < .7")
            state = page.locator("#landing-sheet").evaluate("node => ({opacity: Number(getComputedStyle(node).opacity), filter: getComputedStyle(node).filter, y: new DOMMatrix(getComputedStyle(node).transform).m42})")
            assert 0 < state["opacity"] < 1
            assert state["y"] < 0
            assert "blur(" in state["filter"] and state["filter"] != "blur(0px)"
            expect(page.locator("#app-preview")).to_have_attribute("src", "http://127.0.0.1:18900/index.html")
            page.screenshot(path=str(artifacts / "transition.png"))
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_function("document.querySelector('#landing-sheet').style.opacity === '1'")
            passed("Manual scroll fades, moves up and blurs landing; reverse scroll restores it")

            page.get_by_role("link", name="Open Data Studio", exact=False).click()
            page.wait_for_url("**/index.html")
            expect(page.locator("#row-search")).to_be_enabled()
            assert page.locator("#landing-sheet").count() == 0
            expect(ask(page, "Total revenue")).to_contain_text("$")
            page.locator("#file-input").set_input_files({"name": "landing-check.csv", "mimeType": "text/csv", "buffer": b"customer,spend\nAda,12.5\nLin,20\n"})
            expect(page.locator("#status")).to_have_text('“landing-check.csv” is ready.')
            expect(ask(page, "Total spend")).to_contain_text("$32.50")
            page.screenshot(path=str(artifacts / "app.png"))
            passed("CTA completes handoff to standalone app; browsing, questions and CSV upload work")
            page.go_back(wait_until="domcontentloaded")
            expect(page.get_by_role("heading", level=1)).to_be_visible()
            page.wait_for_function("scrollY === 0 && document.querySelector('#landing-sheet').style.opacity === '1'")
            passed("Browser Back restores landing without an automatic redirect loop")

            mobile = context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            mobile_page = mobile.new_page()
            mobile_page.on("pageerror", lambda error: errors.append(str(error)))
            mobile_page.goto("http://127.0.0.1:18900/landing/")
            mobile_page.evaluate("document.fonts.ready")
            assert mobile_page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            mobile_page.screenshot(path=str(artifacts / "mobile.png"), full_page=True)
            mobile_page.get_by_role("link", name="Open Data Studio", exact=False).click()
            mobile_page.wait_for_url("**/index.html")
            expect(mobile_page.locator("#row-search")).to_be_enabled()
            passed("Touch/mobile layout and CTA transition reach the working app")

            reduced = context(viewport={"width": 1366, "height": 768}, reduced_motion="reduce")
            reduced_page = reduced.new_page()
            reduced_page.goto("http://127.0.0.1:18900/landing/")
            assert reduced_page.locator("#landing-sheet").evaluate("node => getComputedStyle(node).filter") == "none"
            reduced_page.get_by_role("link", name="Open app", exact=False).click()
            reduced_page.wait_for_url("**/index.html")
            expect(reduced_page.locator("#row-search")).to_be_enabled()
            passed("Reduced-motion preference opens the app without scroll or blur animation")

            no_js = context(java_script_enabled=False, viewport={"width": 390, "height": 844})
            no_js_page = no_js.new_page()
            no_js_page.goto("http://127.0.0.1:18900/landing/")
            no_js_page.get_by_role("link", name="Open Data Studio", exact=False).click()
            no_js_page.wait_for_url("**/index.html")
            passed("Without JavaScript, CTA remains a normal link to the original app")
            assert not errors, errors
            passed("No JavaScript exceptions")
            browser.close()
        (artifacts / "results.json").write_text(json.dumps({"passed": checks, "failed": []}, indent=2), encoding="utf-8")
        print(f"Artifacts: {artifacts}", flush=True)
    finally:
        print(f"Artifacts: {artifacts}", flush=True)
        server.should_exit = True
        static.shutdown()
        static.server_close()
        api_thread.join(timeout=5)
        static_thread.join(timeout=5)


if __name__ == "__main__":
    main()
