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

