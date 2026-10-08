from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from .plan import Filter, QueryPlan, TimeGroup


class PlanExecutionError(ValueError):
    """A safe, user-facing query-plan error."""


@dataclass(frozen=True)
class ExecutionResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    dataframe: pd.DataFrame
    pandas_steps: list[str] = field(default_factory=list)


def dataframe_page(df: pd.DataFrame, offset: int = 0, limit: int = 100) -> ExecutionResult:
    safe_offset = max(offset, 0)
    safe_limit = min(max(limit, 1), 500)
    page = df.iloc[safe_offset : safe_offset + safe_limit]
    rows = [
        {str(column): _json_value(value) for column, value in record.items()}
        for record in page.to_dict(orient="records")
    ]
    return ExecutionResult(
        columns=[str(column) for column in page.columns],
        rows=rows,
        row_count=len(df),
        truncated=safe_offset + len(page) < len(df),
        dataframe=df,
    )


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


def _pandas_literal(value: Any) -> str:
    if value is pd.NaT:
        return "pd.NaT"
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return f"pd.Timestamp({value.isoformat()!r})"
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return f"float({str(value)!r})"
    return repr(value)


def _apply_filter(frame: pd.DataFrame, item: Filter, steps: list[str] | None = None) -> pd.DataFrame:
    _require_column(item.column, list(frame.columns), "filter")
    series = frame[item.column]
    if item.op == "in":
        if not isinstance(item.value, list):
            raise PlanExecutionError("The 'in' operator requires a list value.")
        values = [_convert_scalar(series, value) for value in item.value]
        mask = series.isin(values)
        expression = f"frame[{item.column!r}].isin([{', '.join(_pandas_literal(value) for value in values)}])"
    elif item.op == "contains":
        if not pd.api.types.is_string_dtype(series.dtype):
            raise PlanExecutionError("The 'contains' operator requires a text column.")
        value = _convert_scalar(series, item.value)
        mask = series.str.contains(value, case=False, regex=False, na=False)
        expression = f"frame[{item.column!r}].str.contains({_pandas_literal(value)}, case=False, regex=False, na=False)"
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
        expression = f"frame[{item.column!r}] {item.op} {_pandas_literal(value)}"
    if steps is not None:
        steps.append(f"frame = frame.loc[{expression}]")
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
    steps = ["frame = df.copy()"]
    for item in plan.filters:
        frame = _apply_filter(frame, item, steps)

    grouped_columns = [item if isinstance(item, str) else item.column for item in plan.group_by]
    for column in grouped_columns:
        _require_column(column, source_columns, "group_by")
    for item in plan.group_by:
        if isinstance(item, TimeGroup):
            series = frame[item.column]
            if not pd.api.types.is_datetime64_any_dtype(series.dtype):
                raise PlanExecutionError(f"Time grain requires a date/time column; '{item.column}' is not date/time.")
            periods = {"day": "D", "week": "W-SUN", "month": "M", "quarter": "Q"}
            frame[item.column] = series.dt.to_period(periods[item.grain]).dt.start_time
            steps.append(f"frame[{item.column!r}] = frame[{item.column!r}].dt.to_period({periods[item.grain]!r}).dt.start_time")
    for item in plan.aggregations:
        _require_column(item.column, source_columns, "aggregation")

    if plan.aggregations:
        named = {
            item.alias: pd.NamedAgg(column=item.column, aggfunc=item.func)
            for item in plan.aggregations
        }
        if grouped_columns:
            result = frame.groupby(grouped_columns, dropna=False).agg(**named).reset_index()
            named_code = ", ".join(f"{item.alias!r}: pd.NamedAgg(column={item.column!r}, aggfunc={item.func!r})" for item in plan.aggregations)
            steps.append(f"result = frame.groupby({grouped_columns!r}, dropna=False).agg(**{{{named_code}}}).reset_index()")
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
            values_code = ", ".join(f"{item.alias!r}: frame[{item.column!r}].{item.func}()" for item in plan.aggregations)
            steps.append(f"result = pd.DataFrame([{{{values_code}}}])")
    else:
        selected = plan.select or source_columns
        for column in selected:
            _require_column(column, source_columns, "select")
        result = frame.loc[:, selected].copy()
        steps.append(f"result = frame.loc[:, {selected!r}].copy()")

    if plan.sort_by:
        _require_column(plan.sort_by, list(result.columns), "sort_by")
        result = result.sort_values(plan.sort_by, ascending=plan.ascending, kind="stable")
        steps.append(f"result = result.sort_values({plan.sort_by!r}, ascending={plan.ascending!r}, kind='stable')")

    page = dataframe_page(result, limit=min(plan.limit, 500))
    return replace(page, pandas_steps=steps)
