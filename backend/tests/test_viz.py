import pandas as pd
import pytest

from backend.app.plan import QueryPlan
from backend.app.viz import choose_viz


def aggregate_plan(group_by: list[object] | None = None, sort_by: str | None = None) -> QueryPlan:
    return QueryPlan(
        group_by=group_by or [],
        aggregations=[{"column": "value", "func": "sum", "alias": "total"}],
        sort_by=sort_by,
    )


@pytest.mark.parametrize("count", [1, 4])
def test_one_row_numeric_result_is_kpi(count: int) -> None:
    frame = pd.DataFrame([{f"metric_{index}": index + 1 for index in range(count)}])
    assert choose_viz(frame, aggregate_plan())["type"] == "kpi"


def test_date_and_numeric_result_is_line() -> None:
    frame = pd.DataFrame({"month": pd.date_range("2026-01-01", periods=3, freq="MS"), "total": [3, 5, 4]})
    assert choose_viz(frame, aggregate_plan([{"column": "month", "grain": "month"}])) == {
        "type": "line", "x": "month", "y": ["total"], "series": None,
    }


def test_one_category_and_numeric_result_is_bar() -> None:
    frame = pd.DataFrame({"region": ["North", "South"], "total": [3.0, 5.0]})
    assert choose_viz(frame, aggregate_plan(["region"])) == {
        "type": "bar", "x": "region", "y": ["total"], "series": None,
    }


def test_two_categories_and_numeric_result_is_grouped_bar() -> None:
    frame = pd.DataFrame({"region": ["North", "North", "South"], "category": ["A", "B", "A"], "total": [3, 5, 4]})
    assert choose_viz(frame, aggregate_plan(["region", "category"])) == {
        "type": "grouped_bar", "x": "region", "y": ["total"], "series": "category",
    }


@pytest.mark.parametrize(
    "frame,plan",
    [
        (pd.DataFrame(), aggregate_plan()),
        (pd.DataFrame({"region": [None], "total": [float("nan")]}), aggregate_plan(["region"])),
        (pd.DataFrame({"region": [f"R{i}" for i in range(16)], "total": range(16)}), aggregate_plan(["region"])),
        (pd.DataFrame({"a": ["x", "y"], "b": ["u", "v"], "c": ["q", "r"], "total": [1, 2]}), aggregate_plan(["a", "b", "c"])),
        (pd.DataFrame({"order_date": pd.date_range("2026-01-01", periods=20), "value": range(20)}), QueryPlan()),
    ],
)
def test_table_fallbacks(frame: pd.DataFrame, plan: QueryPlan) -> None:
    assert choose_viz(frame, plan)["type"] == "table"


def test_two_row_date_result_is_table() -> None:
    frame = pd.DataFrame({"month": pd.date_range("2026-01-01", periods=2, freq="MS"), "total": [3, 5]})
    assert choose_viz(frame, aggregate_plan([{"column": "month", "grain": "month"}]))["type"] == "table"
