# Secure CSV Chatbot

A FastAPI backend turns natural-language questions into a validated JSON query
plan and executes that plan through an allowlist-based Pandas engine. A static
HTML/CSS/JavaScript frontend provides the chat experience. Model output is
always treated as data and is never executed as Python.

The Data Explorer displays the bundled CSV with pagination and accepts custom
UTF-8 CSV uploads. Selecting a dataset switches both the table and chat to that
file. Uploads are kept in memory and removed when the backend restarts.

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
| `GEMINI_BACKUP_API_KEY` | none | Tried immediately on quota/rate-limit errors; reused for subsequent requests |
| `GEMINI_MODEL` | `gemini-3-flash-preview` | Preferred Gemini model |
| `GEMINI_FALLBACK_MODEL` | `gemini-2.5-flash` | Tried on the same key before switching keys |
| `ALLOWED_ORIGINS` | local frontend URLs | Comma-separated CORS origins |
| `CSV_PATH` | `backend/data/sales_data.csv` | CSV file location |

The API accepts questions up to 500 characters and at most six history turns.
Gemini quota detection recognizes HTTP 429 and structured `RESOURCE_EXHAUSTED`
errors. The default order is primary key with Gemini 3 Flash, primary key with
Gemini 2.5 Flash, backup key with Gemini 3 Flash, then backup key with Gemini 2.5
Flash. Quota cooldowns apply to each model/key combination, not the entire key.
A limited combination is skipped until its retry delay expires (60 seconds by
default, at least one hour for a reported daily quota). Each request chooses the
highest-priority available combination, returning to Gemini 3 when its cooldown
expires. All-combination exhaustion returns HTTP 503 with
`error_code: "gemini_quota_exhausted"`, `retry_after`, and a `Retry-After` header.
Connection errors remain HTTP 502 with `error_code: "gemini_connection_error"`;
changing keys cannot fix a blocked network connection. No raw keys or provider
responses are included in public errors. Keys in the same Google Cloud project
share the project's quota.

It rate-limits query requests to 20 per client IP per minute and never returns
more than 500 rows.

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
