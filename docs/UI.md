# CSV Data Studio workspace

The existing static HTML/CSS/JavaScript frontend uses a 56px top bar and a
62/38 table/chat split. Both panels scroll independently. Below 900px they stack
vertically; collapsing chat gives the table the entire workspace.

The table loads all rows using the existing endpoint in batches of 500. Search
and sorting run in the browser across the complete dataset once loading finishes.
Only a window of 100 rows is rendered, so large uploads do not create thousands
of DOM elements. Column types live in sortable headers. The table is read-only.

Dates display as `YYYY-MM-DD`. Numbers use the `en-US` locale regardless of the
browser locale. USD columns and recognizable money column names display with
two decimal places, such as `$2,417.73`. Aggregate aliases inherit their source
column's currency format, except `count` and `nunique`. CSV exports retain raw
numeric values for reuse and normalize ISO dates.

## API addition

Successful `POST /api/query` results include an additive `result_type` field.
They also include `pandas_query`, a Python trace of the actual pandas operations,
recorded alongside execution. It includes converted filter values, date grouping,
aggregations, explicit or automatic sorting, and the displayed-row limit.
`df` refers to the active CSV already loaded and typed by the backend. The
frontend's Show query toggle displays this trace rather than the JSON plan.
The backend still runs validated allowlisted operations; it does not execute
model-generated Python. The existing `plan` remains available for chat history.
Existing `plan`, `columns`, `rows`, `row_count`, `truncated`, and `viz` fields are
preserved. Clarification and error responses are unchanged. Unrelated questions
return HTTP 200 with `{"out_of_scope": true}`; the frontend uses the active
schema and examples to display dataset-specific guidance. An HTTP 422 from plan
generation is a separate failure and must not be interpreted as an unrelated
question.
Gemini errors also include a safe `error_code`: quota exhaustion uses HTTP 503
and `retry_after`, while connection failures use HTTP 502. The chat distinguishes
these from query validation failures.

Classification uses the result's pandas shape/dtypes and whether the validated
plan contains aggregations:

- Empty/all-null results: `table`.
- One row and one column: `value`, including text.
- Row listings without aggregations: `table`.
- One row containing only numeric aggregate metrics: `value`.
- One date column plus numeric aggregate metrics: `time_series`.
- One category plus numeric aggregate metrics, or two categories plus one
  numeric metric: `categorical`.
- Other shapes: `table`.

This preserves row listings as tables even when they contain dates or money.
The previous `viz` classifier and query execution are unchanged. The frontend
can also consume older responses using their `viz` hint.

Chat renders metrics as plain text, categories as bars, time series as lines,
and row listings as compact tables. Charts have a table toggle, full formatted
tooltips, integer tick positions for whole-number data, and PNG downloads with
their title, subtitle, and background. Answers provide Copy; table/chart data
also provide Export CSV. Suggestions disappear after the first question and
reset when a dataset is selected. Requests from a previous dataset are aborted
and cannot enter the new conversation.

## Verification

Run the backend suite using the command in the README. Optional browser checks
use an installed Chrome browser and Playwright:

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe tests\ui_smoke.py
```

The browser script starts isolated servers on ports 18780/18781, uses a
deterministic LLM with the real API and pandas executor, and saves screenshots
and sample downloads in a temporary directory printed at completion. It checks
the 1366×768 layout, 15 visible rows, sticky headers, search/sort, collapse/reopen,
answer types, copy/downloads, uploads, switching datasets during a request, three
responsive sizes, locale-independent formatting, and unavailable Chart.js.

## Limits

Chart.js still loads from the existing CDN. If it cannot load, chart answers
fall back to a readable table with CSV export. Query results and their exports
retain the existing 500-row maximum. Large datasets must finish downloading
before search is enabled; the initial rows are available while loading. Currency
recognition uses existing USD metadata and column names, since uploads do not
declare currency units. Other currencies need explicit metadata in a future
change. On small screens, suggestions wrap within a vertically scrollable area
to keep the composer visible.
