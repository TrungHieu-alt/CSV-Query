from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from .plan import Filter, QueryPlan


class PlanExecutionError(ValueError):
    """A safe, user-facing query-plan error."""


@dataclass(frozen=True)
class ExecutionResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


def _require_column(column: str, columns: list[str], context: str) -> None:
    if column not in columns:
        raise PlanExecutionError(f"Unknown column '{column}' in {context}.")


def _convert_scalar(series: pd.Series, value: Any) -> Any:
    try:
        if pd.api.types.is_datetime64_any_dtype(series.dtype):
            return pd.to_datetime(value, errors="raise")
        if pd.api.types.is_integer_dtype(series.dtype):
            number = pd.to_numeric(value, errors="raise")
            if float(number) % 1:
                raise ValueError("expected an integer")
            return int(number)
        if pd.api.types.is_float_dtype(series.dtype):
            return float(pd.to_numeric(value, errors="raise"))
        if pd.api.types.is_bool_dtype(series.dtype):
            if isinstance(value, bool):
                return value
            normalized = str(value).lower()
            if normalized in {"true", "1"}:
                return True
            if normalized in {"false", "0"}:
                return False
            raise ValueError("expected a boolean")
        return str(value)
    except (TypeError, ValueError) as exc:
        raise PlanExecutionError(f"Invalid value for column '{series.name}'.") from exc


def _apply_filter(frame: pd.DataFrame, item: Filter) -> pd.DataFrame:
    _require_column(item.column, list(frame.columns), "filter")
    series = frame[item.column]
    if item.op == "in":
        if not isinstance(item.value, list):
            raise PlanExecutionError("The 'in' operator requires a list value.")
        values = [_convert_scalar(series, value) for value in item.value]
        mask = series.isin(values)
    elif item.op == "contains":
        if not pd.api.types.is_string_dtype(series.dtype):
            raise PlanExecutionError("The 'contains' operator requires a text column.")
        value = _convert_scalar(series, item.value)
        mask = series.str.contains(value, case=False, regex=False, na=False)
    else:
        value = _convert_scalar(series, item.value)
        operations = {
            "==": lambda: series == value,
            "!=": lambda: series != value,
            ">": lambda: series > value,
            ">=": lambda: series >= value,
            "<": lambda: series < value,
            "<=": lambda: series <= value,
        }
        mask = operations[item.op]()
    return frame.loc[mask]


def _json_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def execute_plan(df: pd.DataFrame, plan: QueryPlan) -> ExecutionResult:
    if plan.clarify:
        raise PlanExecutionError("Clarification plans cannot be executed.")

    source_columns = list(df.columns)
    frame = df.copy()
    for item in plan.filters:
        frame = _apply_filter(frame, item)

    for column in plan.group_by:
        _require_column(column, source_columns, "group_by")
    for item in plan.aggregations:
        _require_column(item.column, source_columns, "aggregation")

    if plan.aggregations:
        named = {
            item.alias: pd.NamedAgg(column=item.column, aggfunc=item.func)
            for item in plan.aggregations
        }
        if plan.group_by:
            result = frame.groupby(plan.group_by, dropna=False).agg(**named).reset_index()
        else:
            values: dict[str, Any] = {}
            for item in plan.aggregations:
                series = frame[item.column]
                aggregators = {
                    "sum": series.sum,
                    "mean": series.mean,
                    "count": series.count,
                    "min": series.min,
                    "max": series.max,
                    "nunique": series.nunique,
                }
                values[item.alias] = aggregators[item.func]()
            result = pd.DataFrame([values])
    else:
        selected = plan.select or source_columns
        for column in selected:
            _require_column(column, source_columns, "select")
        result = frame.loc[:, selected].copy()

    if plan.sort_by:
        _require_column(plan.sort_by, list(result.columns), "sort_by")
        result = result.sort_values(plan.sort_by, ascending=plan.ascending, kind="stable")

    total = len(result)
    limited = result.head(min(plan.limit, 500))
    rows = [
        {str(column): _json_value(value) for column, value in record.items()}
        for record in limited.to_dict(orient="records")
    ]
    return ExecutionResult(
        columns=[str(column) for column in limited.columns],
        rows=rows,
        row_count=total,
        truncated=total > len(limited),
    )
