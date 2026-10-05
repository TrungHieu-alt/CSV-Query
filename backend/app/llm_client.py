from __future__ import annotations

import logging
from typing import Any

import requests


logger = logging.getLogger("csv_chatbot")

class LLMError(RuntimeError):
    pass


GEMINI_QUERY_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "clarify": {"type": "string", "nullable": True},
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
        "limit": {"type": "integer"},
    },
}


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout: int = 60, backup_api_key: str = "") -> None:
        self._api_key = api_key
        self._backup_api_key = backup_api_key if backup_api_key != api_key else ""
        self._model = model
        self._timeout = timeout

    def generate(self, prompt: str) -> str:
        api_keys = [key for key in (self._api_key, self._backup_api_key) if key]
        if not api_keys:
            raise LLMError("Gemini is not configured.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
                "responseSchema": GEMINI_QUERY_PLAN_SCHEMA,
            },
        }
        for index, api_key in enumerate(api_keys):
            try:
                response = requests.post(
                    url,
                    headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                    json=payload,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                data = response.json()
                candidate = data["candidates"][0]
                parts = candidate["content"]["parts"]
                text = "".join(part.get("text", "") for part in parts).strip()
                if not text:
                    raise LLMError("Gemini returned an empty response.")
                return text
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                has_backup = index + 1 < len(api_keys)
                if status == 429 and has_backup:
                    logger.warning("Gemini primary key rate-limited; retrying with the backup key.")
                    continue
                raise LLMError("Gemini request failed.") from exc
            except LLMError:
                raise
            except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
                raise LLMError("Gemini request failed.") from exc
        raise LLMError("Gemini request failed.")
