# Full app flow verification — 2026-10-08

The app passed all checks below after fixing an Excel-only serialization bug.
The original frozen CSV tests and snapshots remain unchanged.

## Results

| Check | Result |
| --- | --- |
| Backend suite | 148 passed, including the 14 frozen CSV tests and 29 Excel tests |
| Dependency consistency | `pip check`: no broken requirements |
| Original Chrome UI suite | Passed |
| CSV/Excel upload Chrome suite | Passed |
| Extended full-flow Chrome suite | 15 check groups passed, no JavaScript exceptions |
| Configured Gemini connection | HTTP 200, `gemini-3-flash-preview` |
| Real CSV question | Total spend returned 32.5 and displayed $32.50 |
| Real Excel question | Total spend returned 32.5 and displayed $32.50 |
| Real Excel monthly question | Correct monthly totals (12.5 and 20), rendered as a line chart |
| Real question after switching sheets | Third worksheet returned its own total, 30, displayed as $30.00 |

Live tests used the actual frontend at `http://localhost:8080`, the configured
API at `http://localhost:8000`, normal browser CORS, and the configured Gemini
credentials. No frontend configuration interception was used for live tests.
The frontend served the same JavaScript as the workspace. Only synthetic
customers were uploaded in the live provider checks. Credentials were not
printed or changed.

## Extended coverage

- Initial schema, rows, suggested questions, and Chart.js loading.
- Bundled sales converted to Excel: same aggregate answer as CSV, date display,
  bar and monthly line charts, chart/table switching, query details, clipboard,
  downloaded PNG signature, and downloaded CSV values checked against pandas.
- A 1,205-row workbook: three API pages loaded, aggregation includes all rows,
  search finds a row beyond the first page, and numeric sorting works.
- Unicode filenames and sheet names, leading empty rows, and empty worksheets.
- Follow-up history, date filters, counts without currency formatting, row
  limits and truncation, empty results, clarification, actual query-plan repair,
  provider quota messages, and a successful subsequent question.
- Seven invalid Excel uploads: malformed ZIP, duplicate headers, empty
  workbook, too many sheets, oversized upload, `.xls`, and `.xlsm`. Each leaves
  the active dataset and selector intact and restores upload controls.
- Switching sheets during a slow question: no stale response enters the new
  conversation; history resets; a new question uses the selected sheet.
- Native time and duration cells, booleans, nulls, and literal `NA` text.
- Desktop and mobile layouts, followed by another successful CSV upload/query.
- A deliberately blocked schema request shows an error; selecting a dataset
  again restores normal browsing and questions.
- The existing UI suite additionally verifies sticky headers, chat collapse,
  responsive sizes, result exports, and the table fallback when Chart.js fails.

## Bug found and fixed

Excel cells containing native Python `time` or `timedelta` values caused upload
to fail with `TypeError: Object of type time/Timedelta is not JSON serializable`.

The fix is confined to `backend/app/excel.py`. Native times are normalized to
ISO time text before inference. Columns whose names trigger CSV date parsing
then follow that same existing conversion rule. Other time columns remain
text. Durations are preserved as ISO duration text, such as `P1DT3H5M0S`.
Three new regression tests cover time queries, unnamed time columns, and
durations with mixed types. The browser flow also verifies their upload,
display, and filtering.

CSV parsing, validation, errors, request behavior, schema generation, rows,
query processing, charts, and layout were not changed. Frozen test files were
compared against commit `22c75e5`; their contents are identical.

## Reproduce

```powershell
.venv/Scripts/python.exe -B -m pytest backend/tests -q -p no:cacheprovider
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -B tests/ui_smoke.py
.venv/Scripts/python.exe -B tests/ui_excel_smoke.py
.venv/Scripts/python.exe -B tests/ui_full_flow.py

# Requires the frontend running on 8080, configured Gemini keys, and network.
# Starts and stops a temporary API on 8000 if no API is already running.
.venv/Scripts/python.exe -B tests/ui_live_flow.py
```

The repeatable suites use a deterministic LLM with the real API, pandas
executor, and Chrome. Live verification performs one connection check and four
Gemini queries; it uses synthetic data and has no fixed expectations about
model-selected aggregation aliases.

The latest extended browser results and screenshots are in
`C:\Users\manhh\AppData\Local\Temp\csv-full-flow-axlo4xzg\`.
The latest live results and screenshots are in
`C:\Users\manhh\AppData\Local\Temp\csv-live-flow-62r1e3_c\`.
These temporary artifacts are not committed.

## Environment and limits

The backend was not running at the start. Live checks started a temporary API
to test the actual 8080/8000 setup and stopped that test server afterward.
After verification, the backend was left running in a hidden background
process (PID 21148). Both `http://localhost:8000/api/health` and the existing
frontend at `http://localhost:8080` return HTTP 200. Local backend logs are
`backend-local.stdout.log` and `backend-local.stderr.log` (not committed).
Docker is unavailable in this environment, so a container image build was
not tested.

Time-only columns using the CSV date-name heuristic acquire the date pandas
uses when parsing time-only text; this preserves CSV behavior. Duration text
can be displayed and filtered, but is not a numeric measure for sum queries.

The suite emits the existing FastAPI TestClient deprecation warning and pandas
format-inference warnings for time-only text. Tests pass with those warnings;
existing dependency pins and CSV conversion rules were preserved.
