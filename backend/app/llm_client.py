from __future__ import annotations

from typing import Any

import requests

from .plan import QueryPlan


class LLMError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout: int = 60) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def generate(self, prompt: str) -> str:
        if not self._api_key:
            raise LLMError("Gemini is not configured.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
                "responseSchema": QueryPlan.model_json_schema(),
            },
        }
        try:
            response = requests.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
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
        except LLMError:
            raise
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError("Gemini request failed.") from exc

