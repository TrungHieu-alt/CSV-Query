from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from backend.app.executor import PlanExecutionError, execute_plan
from backend.app.plan import QueryPlan


@pytest.fixture(scope="module")
def sales() -> pd.DataFrame:
    path = Path(__file__).parents[1] / "data" / "sales_data.csv"
    frame = pd.read_csv(path, encoding="utf-8")
    frame["order_date"] = pd.to_datetime(frame["order_date"])
    return frame


def test_filter_and_select(sales: pd.DataFrame) -> None:
    plan = QueryPlan(filters=[{"column": "region", "op": "==", "value": "Can Tho"}], select=["order_id", "region"], limit=500)
    result = execute_plan(sales, plan)
    assert result.row_count == 98
    assert set(row["region"] for row in result.rows) == {"Can Tho"}


def test_date_range_and_scalar_aggregation(sales: pd.DataFrame) -> None:
    plan = QueryPlan(filters=[{"column": "order_date", "op": ">=", "value": "2025-03-01"}, {"column": "order_date", "op": "<", "value": "2025-04-01"}], aggregations=[{"column": "revenue", "func": "sum", "alias": "total_revenue"}])
    result = execute_plan(sales, plan)
    assert result.rows[0]["total_revenue"] == pytest.approx(73183.35)


def test_group_aggregation_sort_and_limit(sales: pd.DataFrame) -> None:
    plan = QueryPlan(group_by=["product"], aggregations=[{"column": "revenue", "func": "sum", "alias": "total_revenue"}], sort_by="total_revenue", ascending=False, limit=5)
    result = execute_plan(sales, plan)
    assert result.row_count == 8
    assert result.truncated is True
    assert result.rows[0]["product"] == "Smartphone"


@pytest.mark.parametrize(
    "grain,expected_first",
    [("day", "2025-01-01T00:00:00"), ("week", "2024-12-30T00:00:00"), ("month", "2025-01-01T00:00:00"), ("quarter", "2025-01-01T00:00:00")],
)
def test_time_grain_grouping(sales: pd.DataFrame, grain: str, expected_first: str) -> None:
    plan = QueryPlan(
        group_by=[{"column": "order_date", "grain": grain}],
        aggregations=[{"column": "revenue", "func": "sum", "alias": "total_revenue"}],
        sort_by="order_date",
        limit=500,
    )
    result = execute_plan(sales, plan)
    assert result.rows[0]["order_date"] == expected_first
    assert sum(row["total_revenue"] for row in result.rows) == pytest.approx(sales["revenue"].sum())


def test_plain_grouping_still_serializes_as_string(sales: pd.DataFrame) -> None:
    plan = QueryPlan(group_by=["region"], aggregations=[{"column": "revenue", "func": "sum", "alias": "total"}])
    assert plan.model_dump(mode="json")["group_by"] == ["region"]


def test_time_grain_requires_datetime_column(sales: pd.DataFrame) -> None:
    plan = QueryPlan(group_by=[{"column": "region", "grain": "month"}], aggregations=[{"column": "revenue", "func": "sum", "alias": "total"}])
    with pytest.raises(PlanExecutionError, match="requires a date/time column"):
        execute_plan(sales, plan)


def test_bad_time_grain_is_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryPlan(group_by=[{"column": "order_date", "grain": "year"}], aggregations=[{"column": "revenue", "func": "sum", "alias": "total"}])


def test_limit_is_capped(sales: pd.DataFrame) -> None:
    result = execute_plan(sales, QueryPlan(limit=5000))
    assert len(result.rows) == 500
    assert result.truncated is True


def test_unknown_column_is_rejected(sales: pd.DataFrame) -> None:
    with pytest.raises(PlanExecutionError, match="Unknown column"):
        execute_plan(sales, QueryPlan(filters=[{"column": "__class__", "op": "==", "value": "x"}]))


def test_bad_operator_is_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryPlan(filters=[{"column": "region", "op": "apply", "value": "x"}])


def test_bad_function_is_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryPlan(aggregations=[{"column": "revenue", "func": "system", "alias": "x"}])


def test_empty_result(sales: pd.DataFrame) -> None:
    result = execute_plan(sales, QueryPlan(filters=[{"column": "region", "op": "==", "value": "Nowhere"}]))
    assert result.row_count == 0
    assert result.rows == []
