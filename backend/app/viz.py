from __future__ import annotations

from typing import Any

import pandas as pd

from .plan import QueryPlan


def _spec(kind: str, x: str | None = None, y: list[str] | None = None, series: str | None = None) -> dict[str, Any]:
    return {"type": kind, "x": x, "y": y or [], "series": series}


def choose_result_type(result_df: pd.DataFrame, plan: QueryPlan) -> str:
    """Describe result shape while keeping raw row listings as tables."""
    if result_df.empty or result_df.dropna(how="all").empty:
        return "table"
    if result_df.shape == (1, 1):
        return "value"
    if not plan.aggregations:
        return "table"
    numeric = [column for column in result_df if pd.api.types.is_numeric_dtype(result_df[column])]
    dates = [column for column in result_df if pd.api.types.is_datetime64_any_dtype(result_df[column])]
    categories = [column for column in result_df if column not in numeric and column not in dates]
    if len(result_df) == 1 and len(numeric) == len(result_df.columns):
        return "value"
    if len(dates) == 1 and numeric and not categories:
        return "time_series"
    if numeric and not dates and (len(categories) == 1 or (len(categories) == 2 and len(numeric) == 1)):
        return "categorical"
    return "table"


def choose_viz(result_df: pd.DataFrame, plan: QueryPlan) -> dict[str, Any]:
    """Choose a display using result shape and dtypes; never model-authored display code."""
    if result_df.empty or result_df.dropna(how="all").empty:
        return _spec("table")
    if not plan.aggregations:
        return _spec("table")

    numeric = [
        str(column)
        for column in result_df.columns
        if pd.api.types.is_numeric_dtype(result_df[column].dtype) and result_df[column].notna().any()
    ]
    if len(result_df) == 1 and 1 <= len(numeric) <= 4:
        return _spec("kpi", y=numeric)

    dates = [
        str(column)
        for column in result_df.columns
        if pd.api.types.is_datetime64_any_dtype(result_df[column].dtype)
    ]
    if dates and numeric and len(result_df) >= 3:
        return _spec("line", x=dates[0], y=numeric)

    categories = [str(column) for column in result_df.columns if str(column) not in numeric and str(column) not in dates]
    if len(categories) == 1 and len(numeric) == 1 and 2 <= len(result_df) <= 15:
        return _spec("bar", x=categories[0], y=numeric)
    if len(categories) == 2 and len(numeric) == 1 and len(result_df) <= 60:
        return _spec("grouped_bar", x=categories[0], y=numeric, series=categories[1])
    return _spec("table")
