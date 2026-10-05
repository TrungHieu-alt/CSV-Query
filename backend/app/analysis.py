from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .plan import TimeGrain


class AnalysisValidationError(ValueError):
    """A safe validation error for an allowlisted analysis request."""


class PeriodWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    start: date
    end: date

    @model_validator(mode="after")
    def end_must_follow_start(self) -> PeriodWindow:
        if self.end <= self.start:
            raise ValueError("period end must be after start")
        return self


class PeriodCompareParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1)
    period: PeriodWindow
    baseline: PeriodWindow
    grain: TimeGrain


class ContributionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1)
    period: PeriodWindow
    baseline: PeriodWindow
    dimension: str = Field(min_length=1)


class PeriodCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["analysis"]
    tool: Literal["period_compare"]
    params: PeriodCompareParams


class ContributionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["analysis"]
    tool: Literal["contribution"]
    params: ContributionParams


AnalysisRequest = Annotated[PeriodCompareRequest | ContributionRequest, Field(discriminator="tool")]
ANALYSIS_REQUEST_ADAPTER = TypeAdapter(AnalysisRequest)


class MetricValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: float
    baseline: float


class ChangeFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    absolute: float
    percentage: float | None


class SampleSizes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: int = Field(ge=0)
    baseline: int = Field(ge=0)


class RankedContributor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    value: str
    direction: Literal["positive", "negative", "flat"]
    current_value: float
    baseline_value: float
    delta: float
    share_of_total_change: float | None
    sample_sizes: SampleSizes


class Findings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["period_compare", "contribution"]
    metric: str
    date_column: str
    period: PeriodWindow
    baseline: PeriodWindow
    grain: TimeGrain | None = None
    dimension: str | None = None
    values: MetricValues
    change: ChangeFinding
    ranked_contributors: list[RankedContributor] = Field(default_factory=list)
    sample_sizes: SampleSizes
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tool_shape(self) -> Findings:
        if self.tool == "period_compare" and (self.grain is None or self.dimension is not None):
            raise ValueError("period_compare findings require grain and no dimension")
        if self.tool == "contribution" and (self.dimension is None or self.grain is not None):
            raise ValueError("contribution findings require dimension and no grain")
        return self


class AnalysisResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    findings: Findings
    rows: list[dict[str, Any]]
    columns: list[str]
    viz: dict[str, Any]


def _date_column(df: pd.DataFrame) -> str:
    for column in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[column].dtype):
            return str(column)
    raise AnalysisValidationError("Analysis requires a date/time column.")


def _validate_metric(df: pd.DataFrame, metric: str) -> None:
    if metric not in df.columns:
        raise AnalysisValidationError(f"Unknown metric '{metric}'.")
    if not pd.api.types.is_numeric_dtype(df[metric].dtype):
        raise AnalysisValidationError(f"Metric '{metric}' must be numeric.")


def _period_frame(df: pd.DataFrame, date_column: str, window: PeriodWindow) -> pd.DataFrame:
    start = pd.Timestamp(window.start)
    end = pd.Timestamp(window.end)
    return df.loc[(df[date_column] >= start) & (df[date_column] < end)]


def _base_findings(
    request: PeriodCompareRequest | ContributionRequest,
    df: pd.DataFrame,
) -> tuple[str, pd.DataFrame, pd.DataFrame, MetricValues, ChangeFinding, SampleSizes, list[str]]:
    params = request.params
    _validate_metric(df, params.metric)
    date_column = _date_column(df)
    current = _period_frame(df, date_column, params.period)
    baseline = _period_frame(df, date_column, params.baseline)
    values = MetricValues(
        current=float(current[params.metric].sum()),
        baseline=float(baseline[params.metric].sum()),
    )
    absolute = values.current - values.baseline
    percentage = None if values.baseline == 0 else absolute / values.baseline * 100
    change = ChangeFinding(absolute=absolute, percentage=percentage)
    samples = SampleSizes(current=len(current), baseline=len(baseline))
    warnings: list[str] = []
    if samples.current == 0:
        warnings.append(f"No rows were found for {params.period.label}.")
    if samples.baseline == 0:
        warnings.append(f"No rows were found for {params.baseline.label}.")
    if values.baseline == 0:
        warnings.append("Percentage change is unavailable because the baseline value is zero.")
    return date_column, current, baseline, values, change, samples, warnings


def period_compare(df: pd.DataFrame, request: PeriodCompareRequest) -> AnalysisResult:
    date_column, _current, _baseline, values, change, samples, warnings = _base_findings(request, df)
    findings = Findings(
        tool=request.tool,
        metric=request.params.metric,
        date_column=date_column,
        period=request.params.period,
        baseline=request.params.baseline,
        grain=request.params.grain,
        values=values,
        change=change,
        sample_sizes=samples,
        warnings=warnings,
    )
    rows = [{"current_value": values.current}]
    return AnalysisResult(
        findings=findings,
        rows=rows,
        columns=["current_value"],
        viz={"type": "kpi", "x": None, "y": ["current_value"], "series": None},
    )


def _dimension_value(value: Any) -> str:
    return "Unknown" if pd.isna(value) else str(value)


def contribution(df: pd.DataFrame, request: ContributionRequest) -> AnalysisResult:
    params = request.params
    if params.dimension not in df.columns:
        raise AnalysisValidationError(f"Unknown dimension '{params.dimension}'.")
    date_column, current, baseline, values, change, samples, warnings = _base_findings(request, df)
    current_dimensions = current[params.dimension].map(_dimension_value)
    baseline_dimensions = baseline[params.dimension].map(_dimension_value)
    grouped_current = current.assign(_dimension=current_dimensions).groupby("_dimension")[params.metric].agg(["sum", "size"])
    grouped_baseline = baseline.assign(_dimension=baseline_dimensions).groupby("_dimension")[params.metric].agg(["sum", "size"])
    dimension_values = grouped_current.index.union(grouped_baseline.index, sort=False)
    items: list[dict[str, Any]] = []
    for raw_value in dimension_values:
        current_sum = float(grouped_current.loc[raw_value, "sum"]) if raw_value in grouped_current.index else 0.0
        baseline_sum = float(grouped_baseline.loc[raw_value, "sum"]) if raw_value in grouped_baseline.index else 0.0
        current_size = int(grouped_current.loc[raw_value, "size"]) if raw_value in grouped_current.index else 0
        baseline_size = int(grouped_baseline.loc[raw_value, "size"]) if raw_value in grouped_baseline.index else 0
        delta = current_sum - baseline_sum
        share = None if change.absolute == 0 else delta / change.absolute * 100
        value = str(raw_value)
        if current_size < 10 or baseline_size < 10:
            warnings.append(
                f"Thin segment '{value}': current n={current_size}, baseline n={baseline_size} (fewer than 10 rows)."
            )
        items.append({
            "value": value,
            "direction": "positive" if delta > 0 else "negative" if delta < 0 else "flat",
            "current_value": current_sum,
            "baseline_value": baseline_sum,
            "delta": delta,
            "share_of_total_change": share,
            "sample_sizes": SampleSizes(current=current_size, baseline=baseline_size),
        })
    items.sort(key=lambda item: abs(item["delta"]), reverse=True)
    contributors = [RankedContributor(rank=index, **item) for index, item in enumerate(items, start=1)]
    findings = Findings(
        tool=request.tool,
        metric=params.metric,
        date_column=date_column,
        period=params.period,
        baseline=params.baseline,
        dimension=params.dimension,
        values=values,
        change=change,
        ranked_contributors=contributors,
        sample_sizes=samples,
        warnings=warnings,
    )
    rows = [
        {
            params.dimension: item.value,
            "current_value": item.current_value,
            "baseline_value": item.baseline_value,
            "delta": item.delta,
            "share_of_total_change": item.share_of_total_change,
            "current_sample_size": item.sample_sizes.current,
            "baseline_sample_size": item.sample_sizes.baseline,
        }
        for item in contributors
    ]
    return AnalysisResult(
        findings=findings,
        rows=rows,
        columns=[
            params.dimension,
            "current_value",
            "baseline_value",
            "delta",
            "share_of_total_change",
            "current_sample_size",
            "baseline_sample_size",
        ],
        viz={"type": "bar", "x": params.dimension, "y": ["delta"], "series": None},
    )


def run_analysis(df: pd.DataFrame, request: PeriodCompareRequest | ContributionRequest) -> AnalysisResult:
    if isinstance(request, PeriodCompareRequest):
        return period_compare(df, request)
    if isinstance(request, ContributionRequest):
        return contribution(df, request)
    raise AnalysisValidationError("Unknown analysis tool.")


def validate_analysis_request(df: pd.DataFrame, request: PeriodCompareRequest | ContributionRequest) -> None:
    _validate_metric(df, request.params.metric)
    _date_column(df)
    if isinstance(request, ContributionRequest) and request.params.dimension not in df.columns:
        raise AnalysisValidationError(f"Unknown dimension '{request.params.dimension}'.")
