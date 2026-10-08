from typing import Any

import pytest
import requests

from backend.app.llm_client import GEMINI_QUERY_PLAN_SCHEMA, GeminiClient, LLMError


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self) -> dict[str, Any]:
        if self.payload is not None:
            return self.payload
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
    order = generation["responseSchema"]["propertyOrdering"]
    assert order.index("aggregations") < order.index("sort_by")
    assert generation["responseSchema"]["properties"]["limit"]["minimum"] == 1
    assert generation["responseSchema"]["properties"]["limit"]["maximum"] == 500
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


def test_working_backup_is_reused_on_follow_up_requests(monkeypatch: Any) -> None:
    used_keys = []
    def fake_post(_url: str, **kwargs: Any) -> FakeResponse:
        key = kwargs["headers"]["x-goog-api-key"]
        used_keys.append(key)
        return FakeResponse(429 if key == "primary" else 200)
    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    client = GeminiClient("primary", "test", backup_api_key="backup")
    client.generate("question")
    client.generate("follow up")
    assert used_keys == ["primary", "backup", "backup"]


def test_structured_resource_exhausted_switches_key(monkeypatch: Any) -> None:
    used_keys = []
    def fake_post(_url: str, **kwargs: Any) -> FakeResponse:
        used_keys.append(kwargs["headers"]["x-goog-api-key"])
        return FakeResponse(400, {"error": {"status": "RESOURCE_EXHAUSTED"}}) if len(used_keys) == 1 else FakeResponse()
    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    GeminiClient("primary", "test", backup_api_key="backup").generate("question")
    assert used_keys == ["primary", "backup"]


def test_exhausted_keys_are_skipped_until_provider_retry_delay(monkeypatch: Any) -> None:
    clock = [100.0]
    used_keys = []
    def fake_post(_url: str, **kwargs: Any) -> FakeResponse:
        used_keys.append(kwargs["headers"]["x-goog-api-key"])
        if clock[0] < 110:
            return FakeResponse(429, {"error": {"status": "RESOURCE_EXHAUSTED", "details": [{"retryDelay": "10s"}]}})
        return FakeResponse()
    monkeypatch.setattr("backend.app.llm_client.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    client = GeminiClient("primary", "test", backup_api_key="backup")
    for _ in range(2):
        with pytest.raises(LLMError) as captured:
            client.generate("question")
        assert captured.value.code == "gemini_quota_exhausted"
        assert captured.value.retry_after == 10
    assert used_keys == ["primary", "backup"]
    clock[0] = 111
    client.generate("question")
    assert used_keys == ["primary", "backup", "primary"]


def test_daily_quota_is_not_retried_after_a_short_rate_limit_delay(monkeypatch: Any) -> None:
    monkeypatch.setattr("backend.app.llm_client.time.monotonic", lambda: 100.0)
    payload = {"error": {"status": "RESOURCE_EXHAUSTED", "details": [{"retryDelay": "15s"}, {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}]}}
    monkeypatch.setattr("backend.app.llm_client.requests.post", lambda *args, **kwargs: FakeResponse(429, payload))
    with pytest.raises(LLMError) as captured:
        GeminiClient("primary", "test").generate("question")
    assert captured.value.retry_after == 3600


@pytest.mark.parametrize("exception", [requests.ConnectionError("private credential details"), requests.Timeout("private credential details")])
def test_network_errors_are_not_misreported_as_quota(monkeypatch: Any, exception: Exception) -> None:
    calls = []
    def fake_post(_url: str, **kwargs: Any) -> FakeResponse:
        calls.append(kwargs["headers"]["x-goog-api-key"])
        raise exception
    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    with pytest.raises(LLMError) as captured:
        GeminiClient("primary", "test", backup_api_key="backup").generate("question")
    assert captured.value.code == "gemini_connection_error"
    assert "private" not in captured.value.public_message
    assert calls == ["primary"]


@pytest.mark.parametrize("success_at", range(4))
def test_models_are_exhausted_on_primary_before_using_backup(monkeypatch: Any, success_at: int) -> None:
    attempts = []
    expected = [("primary", "gemini-3-flash-preview"), ("primary", "gemini-2.5-flash"),
                ("backup", "gemini-3-flash-preview"), ("backup", "gemini-2.5-flash")]
    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        model = url.split("/models/", 1)[1].split(":", 1)[0]
        attempts.append((kwargs["headers"]["x-goog-api-key"], model))
        generation = kwargs["json"]["generationConfig"]
        if model == "gemini-3-flash-preview":
            assert generation["temperature"] == 1.0
            assert generation["thinkingConfig"] == {"thinkingLevel": "minimal"}
        else:
            assert "thinkingConfig" not in generation
        return FakeResponse(200 if len(attempts) > success_at else 429)
    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    client = GeminiClient("primary", "gemini-3-flash-preview", backup_api_key="backup", fallback_model="gemini-2.5-flash")
    client.generate("question")
    assert attempts == expected[:success_at + 1]
    assert client.active_model == expected[success_at][1]
    client.generate("follow up")
    assert attempts[-1] == expected[success_at]
    assert len(attempts) == success_at + 2


def test_primary_preferred_model_is_tried_again_after_cooldown(monkeypatch: Any) -> None:
    clock = [100.0]
    attempts = []
    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        model = url.split("/models/", 1)[1].split(":", 1)[0]
        attempts.append(model)
        return FakeResponse(429 if model == "gemini-3-flash-preview" and clock[0] == 100 else 200)
    monkeypatch.setattr("backend.app.llm_client.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    client = GeminiClient("primary", "gemini-3-flash-preview", fallback_model="gemini-2.5-flash")
    client.generate("first question")
    assert client.active_model == "gemini-2.5-flash"
    clock[0] = 161
    client.generate("next question")
    assert client.active_model == "gemini-3-flash-preview"
    assert attempts == ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-3-flash-preview"]


def test_all_model_key_routes_are_attempted_once_then_cooled_down(monkeypatch: Any) -> None:
    attempts = []
    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        attempts.append((kwargs["headers"]["x-goog-api-key"], url))
        return FakeResponse(429)
    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    client = GeminiClient("primary", "gemini-3-flash-preview", backup_api_key="backup", fallback_model="gemini-2.5-flash")
    for _ in range(2):
        with pytest.raises(LLMError) as error:
            client.generate("question")
        assert error.value.code == "gemini_quota_exhausted"
    assert len(attempts) == 4
    assert len(set(attempts)) == 4


def test_duplicate_models_do_not_repeat_requests(monkeypatch: Any) -> None:
    attempts = []
    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        attempts.append(url)
        return FakeResponse(429)
    monkeypatch.setattr("backend.app.llm_client.requests.post", fake_post)
    with pytest.raises(LLMError):
        GeminiClient("primary", "gemini-2.5-flash", fallback_model="gemini-2.5-flash").generate("question")
    assert len(attempts) == 1
