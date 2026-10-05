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

# Step 2 plan — deterministic data analysis

1. Preserve the validated query-plan path and detect analysis requests by `mode`.
2. Define strict Pydantic models for tool calls, periods, findings, and narration.
3. Use half-open ISO date ranges so period boundaries are deterministic.
4. Validate tool names, numeric metrics, date ranges, grains, and dimensions.
5. Implement `period_compare` with totals, changes, percentages, and sample sizes.
6. Implement `contribution` with per-dimension deltas and ranked contributors.
7. Generate warnings for missing periods, zero baselines, and segments below ten rows.
8. Keep all arithmetic in trusted Pandas/Python code and serialize exact FINDINGS.
9. Add one grounded narration call whose structured output may only cite FINDINGS.
10. Reject narration containing unsupported numbers and use a deterministic fallback.
11. Return analysis fields additively alongside the existing plan, rows, and viz fields.
12. Render the headline, insights, KPI delta, contribution chart, and sample sizes safely.
13. Add a collapsible evidence panel and deterministic schema-aware follow-up chips.
14. Extend the Gemini response schema without allowing executable expressions.
15. Add offline tool, validation, retry, grounding, security, and golden-number tests.
16. Update README and decisions, run all checks, and commit the Step 2 milestone.
