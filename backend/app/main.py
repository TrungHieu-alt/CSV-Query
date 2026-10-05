from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any, Callable

import pandas as pd
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .datasets import MAX_UPLOAD_BYTES, DatasetError, DatasetRegistry
from .executor import dataframe_page
from .llm_client import GeminiClient, LLMError
from .plan import QueryPlan
from .schema import validate_declared_columns
from .service import QueryService


logger = logging.getLogger("csv_chatbot")


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=1000)


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=6)
    dataset_id: str = Field(default="default", min_length=1, max_length=64, pattern=r"^(default|[a-f0-9]{32})$")


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._requests[key]
            while bucket and bucket[0] <= now - self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


def _load_data(settings: Settings) -> pd.DataFrame:
    if not settings.csv_path.is_file():
        raise RuntimeError(f"CSV file not found: {settings.csv_path}")
    frame = pd.read_csv(settings.csv_path, encoding="utf-8")
    validate_declared_columns(frame)
    if "order_date" in frame.columns:
        frame["order_date"] = pd.to_datetime(frame["order_date"], errors="raise")
    return frame


def create_app(
    settings: Settings | None = None,
    service_factory: Callable[[pd.DataFrame, list[dict[str, Any]]], Any] | None = None,
    llm_client: Any | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    limiter = RateLimiter(app_settings.rate_limit_per_minute)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        frame = _load_data(app_settings)
        client = llm_client or GeminiClient(app_settings.gemini_api_key, app_settings.gemini_model)
        app.state.gemini_client = client
        if service_factory:
            service_builder = service_factory
        else:
            service_builder = lambda dataset, schema: QueryService(dataset, schema, client)
        app.state.datasets = DatasetRegistry(frame, service_builder)
        yield

    app = FastAPI(title="Secure CSV Chatbot", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def rate_limit(request: Request, call_next: Callable[..., Any]):
        if request.url.path in {"/api/query", "/api/datasets"} and request.method == "POST":
            ip = request.client.host if request.client else "unknown"
            if not limiter.allow(ip):
                return JSONResponse(status_code=429, content={"error": "Rate limit exceeded. Try again shortly."})
        return await call_next(request)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health/gemini")
    async def gemini_health(request: Request) -> JSONResponse:
        try:
            raw = request.app.state.gemini_client.generate(
                'Connection check. Return only {"clarify":"Connection successful"}.'
            )
            plan = QueryPlan.model_validate_json(raw)
            if not plan.clarify:
                raise ValueError("Unexpected connection-check response.")
            return JSONResponse(content={
                "status": "ok",
                "provider": "gemini",
                "model": app_settings.gemini_model,
            })
        except Exception:
            return JSONResponse(status_code=502, content={
                "status": "error",
                "provider": "gemini",
                "model": app_settings.gemini_model,
                "error": "Gemini rejected the configured key or model request.",
            })

    @app.get("/api/schema")
    async def schema(request: Request, dataset_id: str = "default") -> JSONResponse:
        try:
            dataset = request.app.state.datasets.get(dataset_id)
            return JSONResponse(content={"columns": dataset.schema, "examples": dataset.examples})
        except DatasetError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.post("/api/datasets")
    async def upload_dataset(
        request: Request,
        filename: str = Query(default="Uploaded CSV", min_length=1, max_length=120),
    ) -> JSONResponse:
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_UPLOAD_BYTES:
                return JSONResponse(status_code=413, content={"error": "The CSV exceeds the 10 MB upload limit."})
        try:
            dataset = request.app.state.datasets.add_upload(filename, bytes(content))
            return JSONResponse(status_code=201, content=request.app.state.datasets.summary(dataset))
        except DatasetError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})

    @app.get("/api/datasets/{dataset_id}/rows")
    async def dataset_rows(
        dataset_id: str,
        request: Request,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> JSONResponse:
        try:
            dataset = request.app.state.datasets.get(dataset_id)
            result = dataframe_page(dataset.frame, offset, limit)
            return JSONResponse(content={
                "dataset_id": dataset.dataset_id,
                "name": dataset.name,
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
                "offset": offset,
                "limit": limit,
                "has_more": result.truncated,
            })
        except DatasetError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.post("/api/query")
    async def query(payload: QueryRequest, request: Request) -> JSONResponse:
        started = time.perf_counter()
        log_data: dict[str, Any] = {"event": "query", "question": payload.question, "dataset_id": payload.dataset_id}
        try:
            service = request.app.state.datasets.get_service(payload.dataset_id)
            result = service.query(
                payload.question,
                [message.model_dump() for message in payload.history],
            )
            log_data["plan"] = result.get("plan")
            return JSONResponse(content=result)
        except DatasetError as exc:
            log_data["error"] = type(exc).__name__
            return JSONResponse(status_code=404, content={"error": str(exc)})
        except LLMError as exc:
            log_data["error"] = type(exc).__name__
            return JSONResponse(status_code=502, content={"error": "The language model request failed."})
        except ValueError as exc:
            log_data["error"] = type(exc).__name__
            return JSONResponse(status_code=422, content={"error": "Unable to produce a valid query plan after one repair attempt."})
        except Exception as exc:
            log_data["error"] = type(exc).__name__
            return JSONResponse(status_code=500, content={"error": "The query could not be completed."})
        finally:
            log_data["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            serialized = json.dumps(log_data, ensure_ascii=False, default=str)
            if app_settings.gemini_api_key:
                serialized = serialized.replace(app_settings.gemini_api_key, "[REDACTED]")
            logger.info(serialized)

    return app


app = create_app()
