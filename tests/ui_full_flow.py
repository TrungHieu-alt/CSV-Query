"""Extended Chrome acceptance flow using the real API and a deterministic LLM.

Run: .venv/Scripts/python.exe -B tests/ui_full_flow.py
"""
from __future__ import annotations

import csv
from datetime import datetime, time as clock_time, timedelta
import functools
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook
import pandas as pd
from playwright.sync_api import expect, sync_playwright
import uvicorn

from backend.app.config import Settings
from backend.app.llm_client import LLMError
from backend.app.main import create_app
from ui_smoke import FixtureLLM, LocalHTTPServer, SimpleHTTPRequestHandler, ask


class FullFlowLLM(FixtureLLM):
    def __init__(self):
        self.contexts = []
        self.repair_pending = False

    def generate(self, prompt):
        if self.repair_pending:
            self.repair_pending = False
            return json.dumps({"select": ["customer", "spend"], "limit": 2})
        context = json.loads(prompt.split("CONTEXT_JSON\n", 1)[1])
        self.contexts.append(context)
        question = context["untrusted_user_question"].lower()
        if question == "repair this question":
            self.repair_pending = True
            return "malformed JSON"
        if question == "clarify this question":
            return json.dumps({"clarify": "Which customer should I filter?"})
        if question == "quota error":
            raise LLMError("Fixture quota", code="gemini_quota_exhausted", retry_after=5)
        if question == "no matching customers":
            return json.dumps({"filters": [{"column": "customer", "op": "==", "value": "absent"}]})
        if question == "only customers after february":
            return json.dumps({
                "filters": [{"column": "joined_date", "op": ">=", "value": "2026-02-01"}],
                "aggregations": [{"column": "spend", "func": "sum", "alias": "total"}],
            })
        if question == "count all customers":
            return json.dumps({"aggregations": [{"column": "customer", "func": "count", "alias": "count"}]})
        if question == "show first 20 customers":
            return json.dumps({"select": ["customer", "joined_date", "spend"], "limit": 20})
        if question == "arrivals after 08:45":
            return json.dumps({"filters": [{"column": "event_time", "op": ">=", "value": "08:45:00"}], "select": ["customer"]})
        return super().generate(prompt)


def workbook(sheets):
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets:
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def main():
    artifacts = Path(tempfile.mkdtemp(prefix="csv-full-flow-"))
    checks = []
    llm = FullFlowLLM()
    app = create_app(Settings(
        gemini_api_key="fixture", gemini_backup_api_key="",
        csv_path=ROOT / "backend/data/sales_data.csv", rate_limit_per_minute=100,
        allowed_origins=["http://127.0.0.1:18800"],
    ), llm_client=llm)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=18801, log_level="error"))
    api_thread = threading.Thread(target=server.run, daemon=True)
    api_thread.start()
    static = LocalHTTPServer(("127.0.0.1", 18800), functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT / "frontend")))
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
            context = browser.new_context(viewport={"width": 1366, "height": 768}, accept_downloads=True)
            context.route("**/config.js*", lambda route: route.fulfill(content_type="application/javascript", body='window.APP_CONFIG = { API_BASE_URL: "http://127.0.0.1:18801" };'))
            context.grant_permissions(["clipboard-read", "clipboard-write"])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto("http://127.0.0.1:18800")
            expect(page.locator("#row-search")).to_be_enabled()
            page.wait_for_function("typeof Chart !== 'undefined'")
            passed("Initial load: schema, rows, examples, Chart.js")

            # Convert real bundled sales to Excel to compare dates, aggregate
            # values, chart data, and exports across both formats end to end.
            sales = pd.read_csv(ROOT / "backend/data/sales_data.csv")
            sales["order_date"] = pd.to_datetime(sales["order_date"])
            sales_rows = [sales.columns.tolist(), *sales.itertuples(index=False, name=None)]
            default_result = ask(page, "Total revenue")
            default_text = default_result.locator(".message-content").inner_text()
            with page.expect_response(lambda response: "/api/datasets?filename=" in response.url and response.request.method == "POST") as upload_response:
                page.locator("#file-input").set_input_files({"name": "sales.xlsx", "mimeType": "application/octet-stream", "buffer": workbook([("Sales", sales_rows)])})
            sales_id = upload_response.value.json()["dataset_id"]
            expect(page.locator("#status")).to_have_text('“sales.xlsx – Sales” is ready.')
            expect(page.locator("#data-summary")).to_have_text(f"{len(sales):,} rows · 8 columns")
            assert ask(page, "Total revenue").locator(".message-content").inner_text() == default_text
            passed("Excel sales dataset matches bundled CSV total and date display")

            result = ask(page, "Top 5 products by revenue")
            expect(result.locator("canvas")).to_be_visible()
            result.get_by_role("button", name="View as table").click()
            expect(result.locator("tbody tr")).to_have_count(5)
            with page.expect_download() as download:
                result.get_by_role("button", name="Export CSV").click()
            download.value.save_as(artifacts / "excel-top-products.csv")
            with (artifacts / "excel-top-products.csv").open(encoding="utf-8-sig", newline="") as source:
                exported = list(csv.DictReader(source))
            expected = sales.groupby("product")["revenue"].sum().sort_values(ascending=False).head(5)
            assert [row["product"] for row in exported] == expected.index.tolist()
            for row, value in zip(exported, expected.tolist()):
                assert abs(float(row["total_revenue"]) - value) < .000001
            result.get_by_role("button", name="Copy", exact=True).click()
            expect(result.get_by_role("button", name="Copied")).to_be_visible()
            assert "Total Revenue" in page.evaluate("navigator.clipboard.readText()")
            result.get_by_role("button", name="View as chart").click()
            with page.expect_download() as download:
                result.get_by_role("button", name="Download chart (PNG)").click()
            download.value.save_as(artifacts / "excel-chart.png")
            assert (artifacts / "excel-chart.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            result.get_by_role("button", name="Show query", exact=True).click()
            expect(result.locator("code")).to_contain_text("groupby")
            passed("Excel bar chart, table toggle, CSV values, clipboard, PNG, query display")
            line = ask(page, "Revenue over time")
            expect(line.locator("canvas")).to_be_visible()
            assert line.locator("canvas").evaluate("canvas => Chart.getChart(canvas).config.type") == "line"
            passed("Native Excel dates support monthly time-series chart")

            customers = [["customer", "joined_date", "spend"]]
            customers.extend([[f"Customer {index:04d}", datetime(2026, 1 if index < 1000 else 2, 2), index + .5] for index in range(1205)])
            unicode_name = "khách hàng.xlsx"
            with page.expect_response(lambda response: "/api/datasets?filename=" in response.url and response.request.method == "POST") as uploaded:
                page.locator("#file-input").set_input_files({"name": unicode_name, "mimeType": "application/octet-stream", "buffer": workbook([("Khách hàng", [[], [], *customers]), ("Empty", []), ("Other", [["customer", "spend"], ["Only other sheet", 999]])])})
            body = uploaded.value.json()
            expect(page.locator("#status")).to_have_text(f'“{unicode_name} – Khách hàng” is ready.')
            expect(page.locator("#row-search")).to_be_enabled()
            expect(page.locator("#data-summary")).to_have_text("1,205 rows · 3 columns")
            assert len(body["datasets"]) == 2
            assert page.evaluate("allRows.length") == 1205
            customer_id = body["dataset_id"]
            other_id = body["datasets"][1]["dataset_id"]
            page.locator("#row-search").fill("Customer 1204")
            expect(page.locator("#row-status")).to_have_text("1 matching rows")
            expect(page.locator("#data-table")).to_contain_text("$1,204.50")
            page.locator("#row-search").fill("")
            page.get_by_role("button", name="Sort by spend", exact=True).click()
            page.get_by_role("button", name="Sort by spend", exact=True).click()
            expect(page.locator("#data-table tbody tr").first).to_contain_text("Customer 1204")
            passed("Unicode names, leading empty rows, empty sheets, 3 row pages, search and numeric sorting")

            result = ask(page, "Total spend")
            expected_total = sum(row[2] for row in customers[1:])
            expect(result.locator(".message-content")).to_contain_text(f"${expected_total:,.2f}")
            result = ask(page, "Only customers after February")
            expected_february = sum(row[2] for row in customers[1001:])
            expect(result.locator(".message-content")).to_contain_text(f"${expected_february:,.2f}")
            assert llm.contexts[-1]["recent_history"]
            result = ask(page, "Count all customers")
            expect(result.locator(".message-content")).to_contain_text("1,205")
            assert "$" not in result.locator(".message-content").inner_text()
            passed("Full-dataset aggregation, follow-up date filter, history, count formatting")

            result = ask(page, "Show first 20 customers")
            expect(result.locator("tbody tr")).to_have_count(20)
            expect(result.locator(".truncation-note")).to_contain_text("1,205")
            passed("Row question uses plan limit and shows truncation")
            expect(ask(page, "No matching customers")).to_contain_text("No matching rows")
            expect(ask(page, "Clarify this question")).to_contain_text("Which customer should I filter?")
            expect(ask(page, "Repair this question").locator("tbody tr")).to_have_count(2)
            expect(ask(page, "Quota error")).to_contain_text("Try again in about 5 seconds")
            expect(ask(page, "Total spend")).to_contain_text(f"${expected_total:,.2f}")
            passed("No results, clarification, real query repair, quota message, subsequent recovery")

            # All upload failures must leave the active workbook and selector
            # intact, then a valid upload must still succeed.
            count_before = page.locator("#dataset-select option").count()
            invalids = [
                ("broken.xlsx", b"not a zip", "could not be parsed"),
                ("duplicate.xlsx", workbook([("Bad", [["name", "name"], ["a", "b"]])]), "non-empty, unique"),
                ("empty.xlsx", workbook([("Empty", [])]), "no non-empty sheets"),
                ("too-many.xlsx", workbook([(f"Sheet{i}", [["value"], [i]]) for i in range(11)]), "10-sheet limit"),
                ("large.xlsx", b"x" * (10 * 1024 * 1024 + 1), "10 MB upload limit"),
                ("old.xls", b"unused", "Only .xlsx"),
                ("macro.xlsm", b"unused", "Only .xlsx"),
            ]
            for filename, content, message in invalids:
                page.locator("#file-input").set_input_files({"name": filename, "mimeType": "application/octet-stream", "buffer": content})
                expect(page.locator("#status")).to_contain_text(message)
                expect(page.locator("#dataset-select option")).to_have_count(count_before)
                assert page.locator("#dataset-select").input_value() == customer_id
                expect(page.locator("#upload-button")).to_be_enabled()
            passed("Seven invalid Excel uploads preserve active dataset and recover upload controls")

            page.locator("#question-input").fill("slow")
            page.get_by_role("button", name="Send", exact=True).click()
            page.locator("#dataset-select").select_option(other_id)
            expect(page.locator("#row-search")).to_be_enabled()
            page.wait_for_timeout(700)
            expect(page.locator(".message.assistant")).to_have_count(1)
            expect(ask(page, "Total spend")).to_contain_text("$999.00")
            assert not llm.contexts[-1]["recent_history"]
            passed("Switching sheets cancels stale response and resets conversation history")

            page.locator("#dataset-select").select_option(sales_id)
            expect(page.locator("#row-search")).to_be_enabled()
            expect(ask(page, "Total revenue").locator(".message-content")).to_have_text(default_text)
            page.screenshot(path=str(artifacts / "excel-desktop.png"))
            for width, height in [(390, 844), (360, 640)]:
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                expect(page.locator("#send-button")).to_be_in_viewport()
                expect(page.locator("#question-input")).to_be_in_viewport()
            page.screenshot(path=str(artifacts / "excel-mobile.png"))
            passed("Excel dataset retains responsive table and chat layout")

            page.set_viewport_size({"width": 1366, "height": 768})
            typed_rows = [
                ["customer", "event_time", "shift", "duration", "active", "spend"],
                ["Ada", clock_time(8, 30), clock_time(8, 30), timedelta(hours=27, minutes=5), True, 12.5],
                ["Lin", clock_time(9, 45), clock_time(9, 45), None, False, 20],
            ]
            page.locator("#file-input").set_input_files({"name": "types.xlsx", "mimeType": "application/octet-stream", "buffer": workbook([("Types", typed_rows)])})
            expect(page.locator("#status")).to_have_text('“types.xlsx – Types” is ready.')
            expect(page.locator("#data-table")).to_contain_text("08:30:00")
            expect(page.locator("#data-table")).to_contain_text("P1DT3H5M0S")
            expect(ask(page, "Arrivals after 08:45")).to_contain_text("Lin")
            assert "Ada" not in page.locator(".message.assistant").last.inner_text()
            passed("Native Excel times, durations, booleans and nulls upload, display and query")

            page.locator("#file-input").set_input_files({"name": "again.csv", "mimeType": "text/csv", "buffer": b"customer,joined_date,spend\nAda,2026-01-02,12.5\nLin,2026-02-03,20\n"})
            expect(page.locator("#status")).to_have_text('“again.csv” is ready.')
            expect(ask(page, "Total spend")).to_contain_text("$32.50")
            passed("CSV upload and question still work after Excel uploads and failures")

            # Loading failures must be visible and retryable without changing
            # the application's existing CSV error handling.
            page.route("**/api/schema?dataset_id=default", lambda route: route.abort())
            page.locator("#dataset-select").select_option("default")
            expect(page.locator("#data-status")).to_contain_text("Cannot reach the API")
            page.unroute("**/api/schema?dataset_id=default")
            page.locator("#dataset-select").select_option(customer_id)
            expect(page.locator("#row-search")).to_be_enabled()
            page.locator("#dataset-select").select_option("default")
            expect(page.locator("#row-search")).to_be_enabled()
            passed("Network load failure surfaces and dataset selection recovers")
            assert not errors, errors
            passed("No JavaScript exceptions during the full flow")
            browser.close()
        (artifacts / "results.json").write_text(json.dumps({"passed": checks, "failed": []}, indent=2), encoding="utf-8")
        print(f"Artifacts: {artifacts}", flush=True)
    finally:
        server.should_exit = True
        static.shutdown()
        static.server_close()
        api_thread.join(timeout=5)
        static_thread.join(timeout=5)


if __name__ == "__main__":
    main()
