# Decisions

1. The backend copies the existing CSV into `backend/data/` so the legacy app
   remains runnable until cleanup and the container has a self-contained data
   path.
2. Query plans use a uniform object shape. A clarification may be represented
   by only `clarify`; all execution fields otherwise use safe defaults.
3. Results are always tabular JSON. Scalar aggregations return a one-row table,
   making the API and frontend rendering consistent.
4. Rate limiting is process-local and per client IP. This is intentionally
   simple for the demo; production multi-worker deployments need shared state.
5. The frontend is served by nginx in Docker and uses `frontend/config.js` for
   the API base URL. Local file/static-server use defaults to
   `http://localhost:8000`.
6. Only low-cardinality string columns expose allowed values. Identifier-like
   columns such as `order_id` are omitted to keep schema responses and prompts
   compact.
7. Uploaded CSV files are UTF-8, limited to 10 MB, 100,000 rows, and 100
   columns. They are held in process memory under random dataset IDs and vanish
   when the backend restarts; this avoids silently persisting user data.
8. Date-like uploaded columns are converted only when their names indicate a
   date/time and every non-empty value parses successfully.
9. Time-grain grouping accepts either the original string column form or a
   strict `{column, grain}` object. Weeks start on Monday; month and quarter
   labels use the first calendar day, producing stable ISO date values.
10. Visualization selection is deterministic and uses the full computed result
    before the response limit is applied. Raw-row queries always remain tables.
11. Unsorted single-category bars are displayed in descending metric order;
    an explicit query-plan sort is never replaced.
12. Visualization metadata uses `x` and `series` column names plus a `y` list,
    which supports one or several KPI/line metrics without changing the shape.
13. Chart.js is the only new browser dependency and is pinned to version 4.4.7
    from jsDelivr. No Python dependency was needed for Step 1.
14. CSV downloads contain the returned result page (at most 500 rows), matching
    exactly what the user can inspect in the fallback table.
15. Multi-turn history stores the previous validated plan, not just a row-count
    label, so follow-up references remain grounded. It is capped at the existing
    1,000-character message limit.
16. A response consisting solely of a `json` Markdown fence is unwrapped and
    still fully validated as data. Validation details are supplied only to the
    repair prompt; public API errors remain generic.
17. Gemini key failover is attempted once and only for an HTTP 429 from the
    primary key. Authentication, malformed responses, and network failures do
    not trigger failover because another credential would not reliably fix them.
    Identical keys are deduplicated, and both configured keys are redacted from
    application logs.
