from typing import Any

from backend.app.llm_client import GEMINI_QUERY_PLAN_SCHEMA, GeminiClient


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

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
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert captured["timeout"] == 60
