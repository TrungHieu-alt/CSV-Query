# Step 1 plan — richer data display

1. Preserve the existing query response fields and add visualization metadata.
2. Extend the query-plan schema with a validated date-grain group object.
3. Continue accepting plain string entries in `group_by` for compatibility.
4. Validate grouped columns against the source DataFrame at execution time.
5. Bucket datetime columns by day, week, month, or quarter in trusted Pandas code.
6. Keep the complete result frame internally so visualization selection sees its true shape.
7. Add a deterministic `choose_viz` function with KPI, line, bar, grouped-bar, and table rules.
8. Default unsorted bar results to descending metric order without overriding explicit plan sorts.
9. Add visualization metadata to successful `/api/query` results only.
10. Pin Chart.js in the frontend CDN URL and render charts without HTML injection.
11. Add KPI, chart/table toggle, safe formatting, long-label tooltips, and empty-state rendering.
12. Add client-side CSV download for every query result.
13. Show accurate truncation notices while retaining the table fallback.
14. Unit-test every visualization decision, time grains, validation, sorting, and API compatibility.
15. Run the complete offline test suite and review the diff for unsafe execution primitives.
16. Record design choices in `docs/DECISIONS.md`, then commit the Step 1 milestone.
