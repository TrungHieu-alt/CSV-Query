from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any

import requests


logger = logging.getLogger("csv_chatbot")

class LLMError(RuntimeError):
    def __init__(self, message: str, code: str = "gemini_request_failed", retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after

    @property
    def public_message(self) -> str:
        return {
            "gemini_quota_exhausted": "Gemini quota or rate limit reached for all configured API keys. Please try again later.",
            "gemini_connection_error": "Cannot connect to Gemini. Check the backend's network connection.",
            "gemini_not_configured": "Gemini API keys are not configured.",
        }.get(self.code, "The language model request failed.")


def _quota_cooldown(response: Any) -> float | None:
    """Recognize Google's structured quota error without logging response bodies."""
    try:
        payload = response.json()
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        if not isinstance(error, dict):
            error = {}
    except (ValueError, TypeError):
        error = {}
    if response.status_code != 429 and error.get("status") != "RESOURCE_EXHAUSTED":
        return None
    delay = 60.0
    details = error.get("details", [])
    for detail in details if isinstance(details, list) else []:
        if not isinstance(detail, dict):
            continue
        try:
            retry = float(str(detail.get("retryDelay", "0")).removesuffix("s"))
            if math.isfinite(retry) and retry > 0:
                delay = retry
        except (ValueError, TypeError):
            pass
        violations = detail.get("violations", [])
        for violation in violations if isinstance(violations, list) else []:
            if isinstance(violation, dict) and "perday" in str(violation.get("quotaId", "")).lower():
                delay = max(delay, 3600.0)
    try:
        retry_header = float(getattr(response, "headers", {}).get("Retry-After", "0"))
        if math.isfinite(retry_header) and retry_header > 0:
            delay = max(delay, retry_header)
    except (ValueError, TypeError):
        pass
    return max(1.0, delay)


GEMINI_QUERY_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    # Define aggregate aliases before referring to them in sort_by.
    "propertyOrdering": ["clarify", "out_of_scope", "filters", "group_by", "aggregations", "select", "sort_by", "ascending", "limit"],
    "properties": {
        "clarify": {"type": "string", "nullable": True},
        "out_of_scope": {"type": "boolean"},
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "op": {"type": "string", "enum": ["==", "!=", ">", ">=", "<", "<=", "in", "contains"]},
                    "value": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "number"},
                            {"type": "boolean"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                },
                "required": ["column", "op", "value"],
            },
        },
        "group_by": {
            "type": "array",
            "items": {
                "anyOf": [
                    {"type": "string"},
                    {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "grain": {"type": "string", "enum": ["day", "week", "month", "quarter"]},
                        },
                        "required": ["column", "grain"],
                    },
                ]
            },
        },
        "aggregations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "func": {"type": "string", "enum": ["sum", "mean", "count", "min", "max", "nunique"]},
                    "alias": {"type": "string"},
                },
                "required": ["column", "func", "alias"],
            },
        },
        "select": {"type": "array", "items": {"type": "string"}},
        "sort_by": {"type": "string", "nullable": True},
        "ascending": {"type": "boolean"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
    },
}


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout: int = 60, backup_api_key: str = "", fallback_model: str | None = None) -> None:
        self._api_key = api_key
        self._backup_api_key = backup_api_key if backup_api_key != api_key else ""
        self._model = model
        self._timeout = timeout
        self._keys = list(dict.fromkeys(key for key in (api_key, self._backup_api_key) if key))
        self._models = list(dict.fromkeys(name for name in (model, fallback_model) if name))
        self._routes = [(index, name) for index in range(len(self._keys)) for name in self._models]
        self._active_model = model
        self._blocked_until: dict[tuple[int, str], float] = {}
        self._key_lock = threading.Lock()

    @property
    def active_model(self) -> str:
        with self._key_lock:
            return self._active_model

    def _available_routes(self) -> list[tuple[int, str]]:
        with self._key_lock:
            now = time.monotonic()
            return [route for route in self._routes if self._blocked_until.get(route, 0) <= now]

    def _quota_error(self) -> LLMError:
        with self._key_lock:
            remaining = min(self._blocked_until.values(), default=time.monotonic() + 60) - time.monotonic()
        return LLMError("Gemini request failed: all configured keys are quota-limited.",
                        code="gemini_quota_exhausted", retry_after=max(1, math.ceil(remaining)))

    def generate(self, prompt: str) -> str:
        if not self._keys:
            raise LLMError("Gemini is not configured.", code="gemini_not_configured")
        available_routes = self._available_routes()
        if not available_routes:
            raise self._quota_error()
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
                "responseSchema": GEMINI_QUERY_PLAN_SCHEMA,
            },
        }
        for index, model in available_routes:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            generation = payload["generationConfig"]
            if model.startswith("gemini-3"):
                generation["temperature"] = 1.0
                generation["maxOutputTokens"] = 2048
                generation["thinkingConfig"] = {"thinkingLevel": "minimal"}
            else:
                generation["temperature"] = 0
                generation["maxOutputTokens"] = 1024
                generation.pop("thinkingConfig", None)
            try:
                response = requests.post(
                    url,
                    headers={"Content-Type": "application/json", "x-goog-api-key": self._keys[index]},
                    json=payload,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                data = response.json()
                candidate = data["candidates"][0]
                parts = candidate["content"]["parts"]
                text = "".join(part.get("text", "") for part in parts if not part.get("thought", False)).strip()
                if not text:
                    raise LLMError("Gemini returned an empty response.")
                with self._key_lock:
                    self._active_model = model
                    self._blocked_until.pop((index, model), None)
                return text
            except requests.HTTPError as exc:
                cooldown = _quota_cooldown(exc.response) if exc.response is not None else None
                if cooldown is not None:
                    with self._key_lock:
                        self._blocked_until[(index, model)] = time.monotonic() + cooldown
                    logger.warning("Gemini key %d model %s quota/rate-limited; trying the next available model/key.", index + 1, model)
                    continue
                raise LLMError("Gemini request failed.") from exc
            except LLMError:
                raise
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise LLMError("Gemini connection failed.", code="gemini_connection_error") from exc
            except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
                raise LLMError("Gemini request failed.") from exc
        raise self._quota_error()
