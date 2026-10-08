"""Browser acceptance checks; requires optional playwright and installed Chrome.

Run from the repository root: .venv/Scripts/python.exe tests/ui_smoke.py
Uses a deterministic LLM with the real API, executor, and uploaded datasets.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from socketserver import TCPServer
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn
from playwright.sync_api import sync_playwright, expect

expect.set_options(timeout=15000)

from backend.app.config import Settings
from backend.app.main import create_app


class LocalHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # Avoid reverse DNS on Windows machines with non-UTF-8 hostnames.
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


class FixtureLLM:
    def generate(self, prompt: str) -> str:
        question = json.loads(prompt.split("CONTEXT_JSON\n", 1)[1])["untrusted_user_question"].lower()
        plan = {"clarify": None, "filters": [], "group_by": [], "aggregations": [], "select": [], "sort_by": None, "ascending": True, "limit": 50}
        if "top 5" in question:
            plan.update(group_by=["product"], aggregations=[{"column": "revenue", "func": "sum", "alias": "total_revenue"}], sort_by="total_revenue", ascending=False, limit=5)
        elif "total revenue" in question:
            plan.update(aggregations=[{"column": "revenue", "func": "sum", "alias": "total_revenue"}])
        elif "over time" in question:
            plan.update(group_by=[{"column": "order_date", "grain": "month"}], aggregations=[{"column": "revenue", "func": "sum", "alias": "total_revenue"}])
        elif "total spend" in question:
            plan.update(aggregations=[{"column": "spend", "func": "sum", "alias": "total"}])
        elif "error" in question:
            raise RuntimeError("INTERNAL STACK TRACE MUST NEVER APPEAR")
        elif "unrelated" in question:
            return json.dumps({"out_of_scope": True})
        elif "invalid plan" in question:
            raise ValueError("Unable to produce a valid query plan after one repair attempt.")
        elif "slow" in question:
            time.sleep(.5)
        return json.dumps(plan)


def ask(page, question):
    count = page.locator(".message.assistant").count()
    page.locator("#question-input").fill(question)
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.locator(".message.assistant")).to_have_count(count + 1)
    expect(page.locator("#send-button")).to_be_enabled()
    expect(page.locator("#data-table")).to_be_visible()
    return page.locator(".message.assistant").last


def main():
    app = create_app(Settings(gemini_api_key="fixture", csv_path=ROOT / "backend/data/sales_data.csv", allowed_origins=["http://127.0.0.1:18780", "http://localhost:18780"]), llm_client=FixtureLLM())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=18781, log_level="error"))
    api_thread = threading.Thread(target=server.run, daemon=True)
    api_thread.start()
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT / "frontend"))
    static = LocalHTTPServer(("127.0.0.1", 18780), handler)
    static_thread = threading.Thread(target=static.serve_forever, daemon=True)
    static_thread.start()
    artifacts = Path(tempfile.mkdtemp(prefix="csv-studio-ui-"))
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="vi-VN", accept_downloads=True)
            context.route("**/config.js*", lambda route: route.fulfill(content_type="application/javascript", body='window.APP_CONFIG = { API_BASE_URL: "http://127.0.0.1:18781" };'))
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto("http://127.0.0.1:18780")
            expect(page.locator("#row-search")).to_be_enabled()
            page.wait_for_function("typeof Chart !== 'undefined'")
            dimensions = page.evaluate("""() => {
              const table = document.querySelector('#data-table').getBoundingClientRect();
              const rows = [...document.querySelectorAll('#data-table tbody tr')].filter(row => {
                const r = row.getBoundingClientRect(); return r.top >= table.top && r.bottom <= table.bottom;
              });
              const chips = document.querySelector('#examples');
              return { pageHeight: document.documentElement.scrollHeight, viewport: innerHeight,
                visibleRows: rows.length, chipsOverflow: chips.scrollWidth > chips.clientWidth,
                dataWidth: table.width, chatWidth: document.querySelector('#chat-panel').getBoundingClientRect().width };
            }""")
            assert dimensions["pageHeight"] == dimensions["viewport"], dimensions
            assert dimensions["visibleRows"] >= 15, dimensions
            assert not dimensions["chipsOverflow"], dimensions
            assert abs(dimensions["dataWidth"] / 1366 - .62) < .01, dimensions
            assert "T00:00:00" not in page.locator("#data-table").inner_text()
            assert "$" in page.locator("#data-table").inner_text()
            page.screenshot(path=str(artifacts / "desktop.png"))
            print("Desktop geometry:", dimensions)

            # The sticky header remains visible while the table scrolls.
            page.locator("#data-table").evaluate("el => el.scrollTop = 1200")
            page.wait_for_timeout(100)
            table_top = page.locator("#data-table").bounding_box()["y"]
            header_top = page.locator("#data-table th").first.bounding_box()["y"]
            assert abs(table_top - header_top) < 2
            page.locator("#row-search").fill("Laptop")
            assert page.locator("#data-table tbody tr").count() > 0
            assert all("Laptop" in text for text in page.locator("#data-table tbody tr").all_inner_texts())
            page.locator("#row-search").fill("no-such-product-123")
            expect(page.locator("#data-table")).to_contain_text("No matching rows")
            page.locator("#row-search").fill("")
            page.get_by_role("button", name="Sort by revenue", exact=True).click()
            values = page.locator("#data-table tbody td:last-child").all_text_contents()
            assert float(values[0].replace("$", "").replace(",", "")) <= float(values[1].replace("$", "").replace(",", ""))
            page.get_by_role("button", name="Sort by revenue", exact=True).click()
            values = page.locator("#data-table tbody td:last-child").all_text_contents()
            assert float(values[0].replace("$", "").replace(",", "")) >= float(values[1].replace("$", "").replace(",", ""))
            page.get_by_role("button", name="Collapse chat panel").click()
            expect(page.locator("#chat-panel")).to_be_hidden()
            assert page.locator("#data-table").bounding_box()["width"] == 1366
            page.get_by_role("button", name="Open chat").click()
            expect(page.locator("#chat-panel")).to_be_visible()

            result = ask(page, "Top 5 products by revenue")
            expect(result.locator("canvas")).to_be_visible()
            result.get_by_role("button", name="Show query", exact=True).click()
            expect(result.locator(".query-details")).to_be_visible()
            expect(result.locator("code")).to_contain_text(".groupby(['product']")
            expect(result.locator("code")).to_contain_text("result.sort_values('total_revenue', ascending=False")
            expect(result.locator("code")).to_contain_text("result.iloc[:5]")
            assert '"group_by"' not in result.locator("code").inner_text()
            result.get_by_role("button", name="Hide query", exact=True).click()
            expect(result.locator(".query-details")).to_be_hidden()
            expect(page.locator("#examples")).to_be_hidden()
            result.get_by_role("button", name="View as table").click()
            expect(result.locator("tbody tr")).to_have_count(5)
            result.get_by_role("button", name="View as chart").click()
            rendered = result.locator("canvas").evaluate("""canvas => {
              const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
              let accentPixels = 0;
              for (let i = 0; i < pixels.length; i += 4) {
                if (pixels[i + 1] > pixels[i] + 15 && pixels[i] < 150 && pixels[i + 3] > 200) accentPixels++;
              }
              return {width: canvas.width, height: canvas.height, accentPixels};
            }""")
            assert rendered["accentPixels"] > 100, rendered
            with page.expect_download() as info:
                result.get_by_role("button", name="Download chart (PNG)").click()
            info.value.save_as(artifacts / "chart.png")
            assert (artifacts / "chart.png").stat().st_size > 1000
            with page.expect_download() as info:
                result.get_by_role("button", name="Export CSV").click()
            info.value.save_as(artifacts / "result.csv")
            assert len((artifacts / "result.csv").read_text(encoding="utf-8-sig").splitlines()) == 6
            context.grant_permissions(["clipboard-read", "clipboard-write"])
            result.get_by_role("button", name="Copy", exact=True).click()
            expect(result.get_by_role("button", name="Copied")).to_be_visible()
            assert "Total Revenue" in page.evaluate("navigator.clipboard.readText()")
            value = ask(page, "Total revenue")
            expect(value.locator("canvas")).to_have_count(0)
            expect(value.locator("table")).to_have_count(0)
            assert "$" in value.inner_text()
            line = ask(page, "Revenue over time")
            expect(line.locator("canvas")).to_be_visible()
            assert page.evaluate("Chart.getChart(document.querySelectorAll('canvas')[1]).config.type") == "line"
            rows = ask(page, "Show the first 20 rows")
            expect(rows.locator("table")).to_be_visible()
            assert "T00:00:00" not in rows.inner_text()
            error = ask(page, "error")
            assert "INTERNAL" not in error.inner_text()
            expect(error).to_contain_text("The query could not be completed")
            guidance = ask(page, "unrelated question")
            expect(guidance).to_contain_text("I can only answer questions about this dataset (columns: order_id, order_date, product, category, region, quantity, unit_price, revenue). Try something like 'Total revenue by region'.")
            invalid = ask(page, "invalid plan")
            expect(invalid).to_contain_text("I couldn’t build a valid query")
            assert "I can only answer" not in invalid.inner_text()
            page.screenshot(path=str(artifacts / "chat.png"))

            # Real upload and schema/row retrieval, including alias currency formatting.
            page.locator("#file-input").set_input_files({"name": "customers.csv", "mimeType": "text/csv", "buffer": b"customer,joined_date,spend\nAda,2026-01-02,2417.73\nLin,2026-02-03,20\n"})
            expect(page.locator("#data-title")).to_have_text("customers.csv")
            expect(page.locator("#row-search")).to_be_enabled()
            expect(page.locator("#data-table")).to_contain_text("$2,417.73")
            expect(page.locator("#data-table")).to_contain_text("2026-01-02")
            assert "T00:00:00" not in page.locator("#data-table").inner_text()
            expect(page.locator("#examples")).to_be_visible()
            spend = ask(page, "Total spend")
            expect(spend).to_contain_text("$2,437.73")
            guidance = ask(page, "unrelated question")
            expect(guidance).to_contain_text("I can only answer questions about this dataset (columns: customer, joined_date, spend). Try something like 'Show the first 20 rows'.")
            assert "order_id" not in guidance.inner_text()
            page.locator("#dataset-select").select_option("default")
            expect(page.locator("#data-title")).to_have_text("Bundled sales data")
            expect(page.locator("#row-search")).to_be_enabled()
            expect(page.locator(".message.assistant")).to_have_count(1)

            # A response from a previous dataset must not enter the new conversation.
            page.locator("#question-input").fill("slow")
            page.get_by_role("button", name="Send", exact=True).click()
            uploaded_id = page.locator("#dataset-select option").nth(1).get_attribute("value")
            page.locator("#dataset-select").select_option(uploaded_id)
            expect(page.locator("#row-search")).to_be_enabled()
            page.wait_for_timeout(600)
            expect(page.locator(".message.assistant")).to_have_count(1)
            expect(page.locator("#send-button")).to_be_enabled()

            # Responsive panels fit within the viewport, with no chip or page overflow.
            for width, height in [(899, 768), (390, 844), (360, 640)]:
                page.set_viewport_size({"width": width, "height": height})
                expect(page.locator("#chat-panel")).to_be_visible()
                assert page.locator("#chat-panel").bounding_box()["y"] > page.locator("#data-table").bounding_box()["y"]
                responsive = page.evaluate("""() => ({width: innerWidth, height: innerHeight, scrollHeight: document.documentElement.scrollHeight,
                  boxes: Object.fromEntries(['workspace', 'chat-panel', 'data-table', 'examples', 'question-input', 'send-button'].map(id => {
                    const r = document.getElementById(id).getBoundingClientRect(); return [id, {top: r.top, bottom: r.bottom, height: r.height}];
                  }))})""")
                assert responsive["scrollHeight"] <= responsive["height"], responsive
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.evaluate("document.querySelector('#examples').scrollWidth <= document.querySelector('#examples').clientWidth")
                expect(page.locator("#question-input")).to_be_in_viewport()
                expect(page.locator("#send-button")).to_be_in_viewport()
            page.screenshot(path=str(artifacts / "mobile.png"))
            # Offline Chart.js has an accessible table fallback.
            fallback = context.new_page()
            fallback.route("**/chart.umd.min.js", lambda route: route.abort())
            fallback.goto("http://127.0.0.1:18780")
            expect(fallback.locator("#row-search")).to_be_enabled()
            fallback_result = ask(fallback, "Top 5 products by revenue")
            expect(fallback_result.locator("table")).to_be_visible()
            expect(fallback_result.locator("canvas")).to_have_count(0)
            assert not errors, errors
            browser.close()
            print("PASS: search, sorting, sticky header, collapse/reopen, value/bar/line/table/error answers, PNG/CSV/copy, upload, dataset switch, stale response, responsive sizes, chart fallback")
            print("Artifacts:", artifacts)
    finally:
        static.shutdown()
        server.should_exit = True
        api_thread.join(timeout=5)


if __name__ == "__main__":
    main()

