from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any, Callable

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .llm_client import GeminiClient, LLMError
from .schema import EXAMPLE_QUESTIONS, build_schema, validate_declared_columns
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


def create_app(settings: Settings | None = None, service_factory: Callable[[pd.DataFrame, list[dict[str, Any]]], Any] | None = None) -> FastAPI:
    app_settings = settings or Settings()
    limiter = RateLimiter(app_settings.rate_limit_per_minute)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        frame = _load_data(app_settings)
        schema = build_schema(frame)
        app.state.schema = schema
        if service_factory:
            app.state.query_service = service_factory(frame, schema)
        else:
            client = GeminiClient(app_settings.gemini_api_key, app_settings.gemini_model)
            app.state.query_service = QueryService(frame, schema, client)
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
        if request.url.path == "/api/query" and request.method == "POST":
            ip = request.client.host if request.client else "unknown"
            if not limiter.allow(ip):
                return JSONResponse(status_code=429, content={"error": "Rate limit exceeded. Try again shortly."})
        return await call_next(request)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/schema")
    async def schema(request: Request) -> dict[str, Any]:
        return {"columns": request.app.state.schema, "examples": EXAMPLE_QUESTIONS}

    @app.post("/api/query")
    async def query(payload: QueryRequest, request: Request) -> JSONResponse:
        started = time.perf_counter()
        log_data: dict[str, Any] = {"event": "query", "question": payload.question}
        try:
            result = request.app.state.query_service.query(
                payload.question,
                [message.model_dump() for message in payload.history],
            )
            log_data["plan"] = result.get("plan")
            return JSONResponse(content=result)
        except (LLMError, ValueError) as exc:
            log_data["error"] = type(exc).__name__
            return JSONResponse(status_code=422, content={"error": str(exc)})
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

