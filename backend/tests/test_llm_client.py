from typing import Any

import pytest
import requests

from backend.app.llm_client import GEMINI_QUERY_PLAN_SCHEMA, GeminiClient, LLMError


class FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self) -> dict[str, Any]:
        return {"candidates": [{"content": {"parts": [{"text": '{"clarify":"Which metric?"}'}]}}]}


def test_gemini_request_uses_supported_json_schema(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    result = GeminiClient("test-key", "gemini-test").generate("prompt")

    assert result == '{"clarify":"Which metric?"}'
    generation = captured["json"]["generationConfig"]
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseSchema"] == GEMINI_QUERY_PLAN_SCHEMA
    serialized = str(generation["responseSchema"])
    assert "$defs" not in serialized
    assert "$ref" not in serialized
    assert "additionalProperties" not in serialized
    group_variants = generation["responseSchema"]["properties"]["group_by"]["items"]["anyOf"]
    assert group_variants[1]["properties"]["grain"]["enum"] == ["day", "week", "month", "quarter"]
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert captured["timeout"] == 60


def test_rate_limit_retries_once_with_backup_key(monkeypatch: Any, caplog: Any) -> None:
    used_keys: list[str] = []

    def fake_post(_url: str, **kwargs: Any) -> FakeResponse:
        used_keys.append(kwargs["headers"]["x-goog-api-key"])
        return FakeResponse(429 if len(used_keys) == 1 else 200)

    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    result = GeminiClient("primary-key", "gemini-test", backup_api_key="backup-key").generate("prompt")

    assert result == '{"clarify":"Which metric?"}'
    assert used_keys == ["primary-key", "backup-key"]
    assert "rate-limited" in caplog.text
    assert "primary-key" not in caplog.text
    assert "backup-key" not in caplog.text


def test_non_rate_limit_http_error_does_not_use_backup(monkeypatch: Any) -> None:
    used_keys: list[str] = []

    def fake_post(_url: str, **kwargs: Any) -> FakeResponse:
        used_keys.append(kwargs["headers"]["x-goog-api-key"])
        return FakeResponse(401)

    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    with pytest.raises(LLMError, match="Gemini request failed"):
        GeminiClient("primary-key", "gemini-test", backup_api_key="backup-key").generate("prompt")
    assert used_keys == ["primary-key"]


def test_second_rate_limit_stops_after_backup(monkeypatch: Any) -> None:
    used_keys: list[str] = []

    def fake_post(_url: str, **kwargs: Any) -> FakeResponse:
        used_keys.append(kwargs["headers"]["x-goog-api-key"])
        return FakeResponse(429)

    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    with pytest.raises(LLMError, match="Gemini request failed"):
        GeminiClient("primary-key", "gemini-test", backup_api_key="backup-key").generate("prompt")
    assert used_keys == ["primary-key", "backup-key"]


def test_identical_backup_key_is_not_retried(monkeypatch: Any) -> None:
    calls = 0

    def fake_post(_url: str, **_kwargs: Any) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse(429)

    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    with pytest.raises(LLMError):
        GeminiClient("same-key", "gemini-test", backup_api_key="same-key").generate("prompt")
    assert calls == 1


def test_custom_response_schema_is_used_for_narration(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    schema = {"type": "object", "properties": {"headline": {"type": "string"}}}

    def fake_post(_url: str, **kwargs: Any) -> FakeResponse:
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    GeminiClient("test-key", "gemini-test").generate("prompt", response_schema=schema)
    assert captured["json"]["generationConfig"]["responseSchema"] == schema
