# Excel uploads and CSV compatibility

Implemented on branch `xlsx-upload-support`. The implementation is also present
in the working tree. The current branch and its index were not switched or
staged. A separate Git index recorded a workspace snapshot (`d938fbad`) followed
by the requested tests, backend, and frontend commits.

## Verification

Further testing is recorded in [FULL_FLOW_TEST_REPORT.md](FULL_FLOW_TEST_REPORT.md):
148 backend tests, four browser suites (including live Gemini), and an
Excel-only native time/duration serialization fix. The results below describe
the initial implementation checkpoint.

- Before implementation: 105 existing backend tests passed.
- Before implementation: 14 new CSV characterization tests passed and were
  committed as `22c75e5` with fixed upload/schema/rows and three query snapshots.
- After implementation: all 145 backend tests passed, including those same
  14 CSV tests, unchanged, and 26 Excel tests.
- The existing Chrome UI suite passed: search, sorting, sticky headers, chat,
  value/bar/line/table/error results, exports, dataset switching, stale responses,
  responsive sizes, and chart fallback. Its Chart.js CDN required network access
  for the test run; no frontend dependency or chart code was changed.
- The new Chrome upload checks passed: CSV, a single-sheet workbook, and a
  three-sheet workbook. Each Excel sheet was selected and queried using a mocked
  LLM. CSV URL, request Content-Type, and exact error messages were verified.
- Screenshots from the Excel browser run were visually inspected. They are
  available locally under `.pytest_cache/xlsx-studio-ui-4ygkt5vu/` (not committed).
- Source comparisons confirm that `parse_csv`, `add_upload`, the existing CSV
  endpoint body, and the frontend `uploadCsv` function are unchanged. Schema,
  row serialization, query processing, charts, and layout were not edited.

Reproduce the checks from the repository root:

```powershell
.venv/Scripts/python.exe -B -m pytest backend/tests -q -p no:cacheprovider
.venv/Scripts/python.exe -B tests/ui_excel_smoke.py
.venv/Scripts/python.exe -B tests/ui_smoke.py
```

The browser scripts use the existing optional Playwright installation and Chrome.
They start temporary local servers and use a deterministic LLM without real API
credentials or Gemini requests.

Inspect the preservation evidence:

```powershell
# Empty diff: frozen Step 1 tests and snapshots have not changed.
git diff 22c75e5 xlsx-upload-support -- backend/tests/test_csv_characterization.py backend/tests/snapshots/csv_contract.json

# Only an Excel import/extension dispatch and a new Excel registry method.
git diff d938fbad xlsx-upload-support -- backend/app/main.py backend/app/datasets.py

# No changes to downstream schema, rows, query execution, charts, or styles.
git diff d938fbad xlsx-upload-support -- backend/app/schema.py backend/app/executor.py backend/app/service.py backend/app/plan.py backend/app/viz.py frontend/styles.css

git log --oneline d938fbad..xlsx-upload-support
```

## Files changed

| File | Change |
| --- | --- |
| `backend/app/excel.py` | Independent Excel validation, parsing, and HTTP upload handling |
| `backend/app/datasets.py` | New Excel registry method producing existing Dataset objects |
| `backend/app/main.py` | Dispatch Excel extensions before the existing CSV upload body |
| `backend/requirements.txt` | Add `openpyxl==3.1.5` |
| `backend/tests/test_csv_characterization.py` | Frozen CSV characterization tests |
| `backend/tests/snapshots/csv_contract.json` | Frozen upload, schema, rows, and query snapshots |
| `backend/tests/test_excel.py` | Excel API, parser, date, formula, and safety tests |
| `frontend/app.js` | Separate Excel upload function and extension dispatch |
| `frontend/index.html` | Expand the file input's accepted types |
| `tests/ui_excel_smoke.py` | Browser upload verification |
| `docs/XLSX_UPLOAD.md` | Verification and decisions |

Only `openpyxl==3.1.5` was added as a direct dependency. It installs `et-xmlfile`
as a transitive dependency (2.0.0 in the verification environment). No existing
dependency pins were upgraded. The backend Dockerfile already installs
`backend/requirements.txt`, so rebuilding the image includes the Excel parser
without a Dockerfile edit. A Docker build was not run.

## Excel behavior and decisions for review

- `.xlsx` is dispatched by extension, case-insensitively. `.xls` and `.xlsm`
  return 400 with a conversion message. Other filenames continue through the
  original CSV path, preserving that API's existing extension acceptance.
- Workbooks retain the 10 MiB upload limit (413). Other Excel validation errors
  return 400. ZIP entries are checked before parsing against a 100 MiB total
  uncompressed limit. XML entity declarations and disguised VBA workbooks are
  rejected.
- At most 10 total worksheets, including empty worksheets, are allowed. Every
  non-empty worksheet becomes a dataset named `<filename> – <sheet name>`.
  Hidden worksheets are included. Fully empty or whitespace-only rows and
  columns are dropped. The first remaining row is the header.
- Headers must be non-empty and unique after trimming. `Unnamed:` headers and
  entirely numeric headers are rejected. A header-only sheet is accepted as a
  dataset with zero data rows. All sheets are parsed and validated before any
  dataset is registered, so a bad sheet does not leave partial uploads.
- Each cleaned dataset is limited to 100,000 rows and 100 columns. To prevent
  pandas from allocating enormous arrays for distant sparse cells, source cell
  coordinates are additionally capped at 200,000 rows, 1,000 columns, and a
  rectangular extent of 10,000,100 cells. A workbook within the final row/column
  limits can therefore still be rejected for distant cells; remove those cells
  and try again.
- Excel is read from in-memory bytes via pandas with `openpyxl` in read-only
  mode, with `data_only=True`, `keep_links=False`, and `keep_vba=False`. Formulas
  and macros are never executed, and links are not fetched. A formula without
  a saved cached value is treated as an empty cell; recalculate and save in Excel
  before uploading if needed.
- Native Excel dates use the same `datetime64[us]` dtype as this version's CSV
  date parsing. Text date columns use the existing CSV naming heuristic and
  all-non-null-values conversion rule, copied into the separate Excel parser.
- Native times are converted to ISO time text before inference; named time
  columns then use the CSV conversion rule. Native durations are preserved as
  ISO duration text so uploads, rows, and queries remain JSON-safe.
- The normal upload fields describe the first non-empty sheet. An optional
  `datasets` array is included only when multiple non-empty sheets produce
  datasets; entries contain `dataset_id` and `name`.
- The frontend adds all returned sheet datasets and selects the first. Excel
  errors show the new backend messages. Existing CSV requests, status messages,
  error messages, and the upload function are preserved, including the existing
  invalid-filename message `Choose a UTF-8 CSV file.` for unrelated extensions.
- Existing CSV-facing labels and layout remain unchanged. Dataset storage
  remains in memory and retains the application's existing restart behavior.
- Pre-existing conflict markers in `backend/app/analysis.py` were left intact.
  This module is not imported by the current query pipeline or test suite.
