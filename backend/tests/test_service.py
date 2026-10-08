import json
from pathlib import Path

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
    assert response["viz"]["type"] == "table"
    assert response["result_type"] == "table"
    assert len(client.prompts) == 1


def test_unsorted_bar_is_descending(frame: pd.DataFrame) -> None:
    client = FakeClient([plan(group_by=["region"], aggregations=[{"column": "revenue", "func": "sum", "alias": "total_revenue"}])])
    response = QueryService(frame, [], client).query("revenue by region")
    assert response["viz"]["type"] == "bar"
    assert response["result_type"] == "categorical"
    assert [row["total_revenue"] for row in response["rows"]] == [20.0, 10.0]


def test_explicit_bar_sort_is_preserved(frame: pd.DataFrame) -> None:
    client = FakeClient([plan(group_by=["region"], aggregations=[{"column": "revenue", "func": "sum", "alias": "total_revenue"}], sort_by="total_revenue", ascending=True)])
    response = QueryService(frame, [], client).query("revenue by region ascending")
    assert [row["total_revenue"] for row in response["rows"]] == [10.0, 20.0]


def test_invalid_json_repair_success(frame: pd.DataFrame) -> None:
    client = FakeClient(["not json", plan(select=["region"])])
    response = QueryService(frame, [], client).query("show regions")
    assert response["row_count"] == 2
    assert len(client.prompts) == 2
    assert "Repair the previous plan" in client.prompts[1]


def test_json_code_fence_is_accepted_without_retry(frame: pd.DataFrame) -> None:
    client = FakeClient([f"```json\n{plan(select=['region'])}\n```"])
    response = QueryService(frame, [], client).query("show regions")
    assert response["columns"] == ["region"]
    assert len(client.prompts) == 1


def test_repair_prompt_contains_safe_validation_details(frame: pd.DataFrame) -> None:
    invalid = json.dumps({"clarify": None, "unknown_field": True})
    client = FakeClient([invalid, plan(select=["region"])])
    QueryService(frame, [], client).query("show regions")
    assert "extra_forbidden" in client.prompts[1]
    assert "unknown_field" in client.prompts[1]


def test_follow_up_history_is_included_in_prompt(frame: pd.DataFrame) -> None:
    previous = json.dumps({"summary": "2 results", "last_plan": {"group_by": ["region"]}})
    client = FakeClient([plan(group_by=["region"], aggregations=[{"column": "revenue", "func": "sum", "alias": "total"}])])
    QueryService(frame, [], client).query("sort that descending", [{"role": "assistant", "content": previous}])
    assert "last_plan" in client.prompts[0]
    assert "sort that descending" in client.prompts[0]


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


def test_out_of_scope_does_not_execute_or_attempt_repair(frame: pd.DataFrame) -> None:
    client = FakeClient(['{"out_of_scope":true}'])
    response = QueryService(frame, [], client).query("What is the capital of France?")
    assert response == {"out_of_scope": True}
    assert len(client.prompts) == 1


def test_out_of_scope_cannot_hide_execution_fields() -> None:
    with pytest.raises(ValueError, match="cannot contain execution fields"):
        QueryService._parse('{"out_of_scope":true,"select":["revenue"]}')


def test_top_five_products_returns_ranked_chart_data() -> None:
    frame = pd.read_csv(Path(__file__).parents[1] / "data" / "sales_data.csv")
    client = FakeClient([plan(group_by=["product"], aggregations=[{"column": "revenue", "func": "sum", "alias": "total_revenue"}], sort_by="total_revenue", ascending=False, limit=5)])
    response = QueryService(frame, [], client).query("Top 5 products by revenue")
    assert response["result_type"] == "categorical"
    assert len(response["rows"]) == 5
    expected = frame.groupby("product")["revenue"].sum().nlargest(5)
    assert [row["product"] for row in response["rows"]] == list(expected.index)
    assert [row["total_revenue"] for row in response["rows"]] == pytest.approx(list(expected.values))


@pytest.mark.parametrize("updates", [
    {"group_by": ["region"], "aggregations": [{"column": "revenue", "func": "sum", "alias": "total_revenue"}], "limit": 2},
    {"group_by": ["region"], "aggregations": [{"column": "revenue", "func": "sum", "alias": "total"}], "sort_by": "total", "ascending": True},
    {"group_by": [{"column": "order_date", "grain": "month"}], "aggregations": [{"column": "revenue", "func": "sum", "alias": "total"}]},
    {"aggregations": [{"column": "revenue", "func": "sum", "alias": "total"}, {"column": "quantity", "func": "nunique", "alias": "unique_quantities"}]},
    {"filters": [{"column": "quantity", "op": "in", "value": ["1", "3"]}]},
    {"filters": [{"column": "quantity", "op": ">=", "value": "2"}], "select": ["quantity"]},
    {"filters": [{"column": "order_date", "op": ">=", "value": "2026-02-01"}]},
    {"filters": [{"column": "region", "op": "contains", "value": "North"}]},
    {"filters": [{"column": "flag", "op": "==", "value": "true"}]},
    {"filters": [{"column": "region", "op": "contains", "value": "__import__('os').system('malicious')"}]},
    {"select": ["customer's name"], "sort_by": "customer's name", "limit": 2},
])
def test_displayed_pandas_query_reproduces_the_response(updates: dict[str, object]) -> None:
    from backend.app.executor import dataframe_page
    frame = pd.DataFrame({
        "region": ["North", "South", "North", None], "revenue": [12.5, 40.0, 10.0, 1.0],
        "quantity": [1, 2, 3, 4], "flag": [True, False, True, False],
        "order_date": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01", "2026-03-02"]),
        "customer's name": ["Ada", "Lin", "O'Neil", "Mai"],
    })
    original = frame.copy(deep=True)
    response = QueryService(frame, [], FakeClient([plan(**updates)])).query("test query")
    namespace = {"df": frame}
    # Only replay this test's server-generated trace, never execute model output.
    exec(response["pandas_query"], namespace)
    replay = dataframe_page(namespace["result"], limit=500)
    assert replay.columns == response["columns"]
    assert replay.rows == response["rows"]
    pd.testing.assert_frame_equal(frame, original)
