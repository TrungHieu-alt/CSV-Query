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
