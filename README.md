# Secure CSV Chatbot

A FastAPI backend turns natural-language questions into a validated JSON query
plan and executes that plan through an allowlist-based Pandas engine. A static
HTML/CSS/JavaScript frontend provides the chat experience. Model output is
always treated as data and is never executed as Python.

The Data Explorer displays the bundled CSV with pagination and accepts custom
UTF-8 CSV uploads. Selecting a dataset switches both the table and chat to that
file. Uploads are kept in memory and removed when the backend restarts.

Query results are displayed automatically as KPI cards, line charts, bar
charts, grouped bars, or tables. Every result can be downloaded as CSV, and
chart results retain a table fallback.

For comparison and contribution questions, the model selects one of two
allowlisted analysis tools. Trusted Pandas code computes the values, changes,
sample sizes, and contributors. A separate model call explains only the
structured findings; an unsupported number causes deterministic narration to
replace the model output.

## Run locally on Windows PowerShell

Prerequisites: Python 3.14 and a Gemini API key. A second key is optional and
is used only when the primary key receives an HTTP 429 rate-limit response.

```powershell
Copy-Item .env.example .env
# Edit .env and replace the placeholder without committing the file.

py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# Terminal 1
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000

# Terminal 2
.\.venv\Scripts\python.exe -m http.server 8080 --directory frontend
```

Open <http://localhost:8080>. API documentation is available at
<http://localhost:8000/docs>.

## Run with Docker

Create `.env` from `.env.example`, set `GEMINI_API_KEY` and optionally
`GEMINI_BACKUP_API_KEY`, then run:

```powershell
docker compose up --build
```

Open <http://localhost:8080>. Stop the stack with `docker compose down`.

## Test

Tests use fake LLM clients and never contact Gemini.

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | none | Required for query requests |
| `GEMINI_BACKUP_API_KEY` | none | Retried once when the primary receives HTTP 429 |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model identifier |
| `ALLOWED_ORIGINS` | local frontend URLs | Comma-separated CORS origins |
| `CSV_PATH` | `backend/data/sales_data.csv` | CSV file location |

The API accepts questions up to 500 characters and at most six history turns.
It rate-limits query requests to 20 per client IP per minute and never returns
more than 500 rows.

Analysis periods are represented as half-open ISO date ranges (`start`
inclusive, `end` exclusive). `period_compare` compares summed numeric metrics;
`contribution` attributes the change to one validated categorical dimension.
Analysis responses add `answer`, `insights`, `findings`, and `follow_ups` while
retaining the normal plan, table, and visualization fields.

## API

- `GET /api/health` — service health
- `GET /api/health/gemini` — make a minimal request to verify the configured
  Gemini key and model; never returns the key
- `GET /api/schema` — generated column metadata and example questions
- `POST /api/datasets?filename=file.csv` — upload raw UTF-8 CSV bytes
- `GET /api/datasets/{dataset_id}/rows` — paginated rows for the explorer
- `POST /api/query` — `{ "question": "...", "history": [] }`

Implementation tradeoffs and production follow-ups are recorded in
[`docs/DECISIONS.md`](docs/DECISIONS.md).

## Legacy app

The original Streamlit implementation is preserved under `legacy/` for
reference. It contains the retired dynamic-expression approach and must not be
used as the production service. To inspect it locally, run
`.\.venv\Scripts\python.exe -m streamlit run legacy\app.py` from the repository
root.
