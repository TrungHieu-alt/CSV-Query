"""Real Chrome checks for CSV and Excel uploads, with a mocked LLM.

Run: .venv/Scripts/python.exe tests/ui_excel_smoke.py
Uses the optional Playwright installation already used by ui_smoke.py.
"""
from __future__ import annotations

import functools
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook
from playwright.sync_api import sync_playwright, expect
import uvicorn

from backend.app.config import Settings
from backend.app.main import create_app
from ui_smoke import FixtureLLM, LocalHTTPServer, SimpleHTTPRequestHandler, ask


def excel_file(names):
    book = Workbook()
    book.remove(book.active)
    for index, name in enumerate(names, 1):
        sheet = book.create_sheet(name)
        sheet.append(["customer", "joined_date", "spend"])
        sheet.append([f"Customer {index}", "2026-01-02", index * 10])
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def main():
    app = create_app(Settings(
        gemini_api_key="fixture", gemini_backup_api_key="",
        csv_path=ROOT / "backend/data/sales_data.csv", rate_limit_per_minute=100,
        allowed_origins=["http://127.0.0.1:18790"],
    ), llm_client=FixtureLLM())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=18791, log_level="error"))
    api_thread = threading.Thread(target=server.run, daemon=True)
    api_thread.start()
    static = LocalHTTPServer(("127.0.0.1", 18790), functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT / "frontend")))
    static_thread = threading.Thread(target=static.serve_forever, daemon=True)
    static_thread.start()
    artifact_root = ROOT / ".pytest_cache"
    artifact_root.mkdir(exist_ok=True)
    artifacts = Path(tempfile.mkdtemp(prefix="xlsx-studio-ui-", dir=artifact_root))
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.route("**/config.js*", lambda route: route.fulfill(content_type="application/javascript", body='window.APP_CONFIG = { API_BASE_URL: "http://127.0.0.1:18791" };'))
            errors = []
            requests = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: requests.append(request) if "/api/datasets?filename=" in request.url else None)
            page.goto("http://127.0.0.1:18790")
            expect(page.locator("#row-search")).to_be_enabled()
            expect(page.locator("#file-input")).to_have_attribute("accept", ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            page.locator("#file-input").set_input_files({
                "name": "customers.csv", "mimeType": "text/csv",
                "buffer": b"customer,joined_date,spend\nAda,2026-01-02,12.5\nLin,2026-02-03,20.0\n",
            })
            expect(page.locator("#status")).to_have_text('“customers.csv” is ready.')
            expect(page.locator("#data-summary")).to_have_text("2 rows · 3 columns")
            expect(page.locator("#dataset-select option")).to_have_count(2)
            assert requests[-1].headers["content-type"] == "text/csv"
            assert requests[-1].url.endswith("/api/datasets?filename=customers.csv")
            assert requests[-1].method == "POST"
            expect(ask(page, "total spend").locator(".message-content")).to_contain_text("32.50")
            page.screenshot(path=str(artifacts / "csv.png"))

            page.locator("#file-input").set_input_files({"name": "one.xlsx", "mimeType": "application/octet-stream", "buffer": excel_file(["Customers"])})
            expect(page.locator("#status")).to_have_text('“one.xlsx – Customers” is ready.')
            expect(page.locator("#data-summary")).to_have_text("1 rows · 3 columns")
            expect(page.locator("#dataset-select option")).to_have_count(3)
            assert requests[-1].headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            expect(ask(page, "total spend").locator(".message-content")).to_contain_text("10")
            page.screenshot(path=str(artifacts / "single-sheet.png"))

            page.locator("#file-input").set_input_files({"name": "three.xlsx", "mimeType": "application/octet-stream", "buffer": excel_file(["First", "Second", "Third"])})
            expect(page.locator("#status")).to_have_text('“three.xlsx – First” is ready.')
            expect(page.locator("#dataset-select option")).to_have_count(6)
            expect(page.locator("#data-title")).to_have_text("three.xlsx – First")
            expect(page.locator("#dataset-select option:checked")).to_have_text("three.xlsx – First")
            for index, name in enumerate(["First", "Second", "Third"], 1):
                page.locator("#dataset-select").select_option(label=f"three.xlsx – {name}")
                expect(page.locator("#row-search")).to_be_enabled()
                expect(page.locator("#data-title")).to_have_text(f"three.xlsx – {name}")
                expect(ask(page, "total spend").locator(".message-content")).to_contain_text(str(index * 10))
            page.screenshot(path=str(artifacts / "three-sheets.png"))

            # Excel errors surface the backend's new messages; CSV's messages
            # retain their current exact text.
            page.locator("#file-input").set_input_files({"name": "bad.xlsx", "mimeType": "application/octet-stream", "buffer": b"not a zip"})
            expect(page.locator("#status")).to_have_text("The file could not be parsed as an .xlsx workbook.")
            page.locator("#file-input").set_input_files({"name": "old.xls", "mimeType": "application/octet-stream", "buffer": b"unused"})
            expect(page.locator("#status")).to_have_text("Only .xlsx files are supported. Save the file as .xlsx and try again.")
            page.locator("#file-input").set_input_files({"name": "bad.csv", "mimeType": "text/csv", "buffer": b"\xff"})
            expect(page.locator("#status")).to_have_text("Could not load this file. Use a valid UTF-8 CSV with a header row.")
            page.locator("#file-input").set_input_files({"name": "large.csv", "mimeType": "text/csv", "buffer": b"x" * (10 * 1024 * 1024 + 1)})
            expect(page.locator("#status")).to_have_text("This CSV exceeds the 10 MB upload limit.")
            page.locator("#file-input").set_input_files({"name": "other.txt", "mimeType": "text/plain", "buffer": b"value\n1\n"})
            expect(page.locator("#status")).to_have_text("Choose a UTF-8 CSV file.")
            assert not errors, errors
            browser.close()
        print("PASS: CSV request and errors unchanged; single-sheet Excel; three-sheet selector and queries; Excel MIME type and errors")
        print(f"Browser screenshots: {artifacts}")
    finally:
        server.should_exit = True
        static.shutdown()
        static.server_close()
        api_thread.join(timeout=5)
        static_thread.join(timeout=5)


if __name__ == "__main__":
    main()
