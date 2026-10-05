import json

import pandas as pd
import pytest

from backend.app.service import QueryService


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self.responses)


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame({"region": ["Hanoi", "Can Tho"], "revenue": [10.0, 20.0]})


def plan(**updates: object) -> str:
    value = {"clarify": None, "filters": [], "group_by": [], "aggregations": [], "select": [], "sort_by": None, "ascending": True, "limit": 50}
    value.update(updates)
    return json.dumps(value)


def test_valid_plan(frame: pd.DataFrame) -> None:
    client = FakeClient([plan(select=["region"])])
    response = QueryService(frame, [], client).query("show regions")
    assert response["columns"] == ["region"]
    assert len(client.prompts) == 1


def test_invalid_json_repair_success(frame: pd.DataFrame) -> None:
    client = FakeClient(["not json", plan(select=["region"])])
    response = QueryService(frame, [], client).query("show regions")
    assert response["row_count"] == 2
    assert len(client.prompts) == 2
    assert "Repair the previous plan" in client.prompts[1]


def test_execution_error_repair_success(frame: pd.DataFrame) -> None:
    bad = plan(select=["__class__"])
    good = plan(select=["region"])
    client = FakeClient([bad, good])
    response = QueryService(frame, [], client).query("show regions")
    assert response["columns"] == ["region"]
    assert len(client.prompts) == 2


def test_repair_failure_stops_after_one_retry(frame: pd.DataFrame) -> None:
    client = FakeClient(["bad", "still bad"])
    with pytest.raises(ValueError, match="after one repair"):
        QueryService(frame, [], client).query("question")
    assert len(client.prompts) == 2


def test_clarification(frame: pd.DataFrame) -> None:
    client = FakeClient([json.dumps({"clarify": "Best by revenue or quantity?"})])
    response = QueryService(frame, [], client).query("best product")
    assert response["clarify"] == "Best by revenue or quantity?"
    assert set(response) == {"clarify"}
    assert len(client.prompts) == 1
