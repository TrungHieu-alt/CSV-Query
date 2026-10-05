from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from backend.app.analysis import (
    ANALYSIS_REQUEST_ADAPTER,
    AnalysisValidationError,
    ContributionRequest,
    Findings,
    PeriodCompareRequest,
    contribution,
    period_compare,
    run_analysis,
)


def window(label: str, start: str, end: str) -> dict[str, str]:
    return {"label": label, "start": start, "end": end}


def compare_request(metric: str = "revenue", period: dict[str, str] | None = None, baseline: dict[str, str] | None = None) -> PeriodCompareRequest:
    return PeriodCompareRequest(
        mode="analysis",
        tool="period_compare",
        params={
            "metric": metric,
            "period": period or window("March 2025", "2025-03-01", "2025-04-01"),
            "baseline": baseline or window("February 2025", "2025-02-01", "2025-03-01"),
            "grain": "month",
        },
    )


def contribution_request(dimension: str = "region") -> ContributionRequest:
    return ContributionRequest(
        mode="analysis",
        tool="contribution",
        params={
            "metric": "revenue",
            "period": window("March 2025", "2025-03-01", "2025-04-01"),
            "baseline": window("February 2025", "2025-02-01", "2025-03-01"),
            "dimension": dimension,
        },
    )


@pytest.fixture(scope="module")
def sales() -> pd.DataFrame:
    path = Path(__file__).parents[1] / "data" / "sales_data.csv"
    frame = pd.read_csv(path, encoding="utf-8")
    frame["order_date"] = pd.to_datetime(frame["order_date"])
    return frame


def test_period_compare_normal(sales: pd.DataFrame) -> None:
    result = period_compare(sales, compare_request())
    march = sales.loc[(sales.order_date >= "2025-03-01") & (sales.order_date < "2025-04-01")]
    february = sales.loc[(sales.order_date >= "2025-02-01") & (sales.order_date < "2025-03-01")]
    assert result.findings.values.current == pytest.approx(march.revenue.sum())
    assert result.findings.values.baseline == pytest.approx(february.revenue.sum())
    assert result.findings.change.absolute == pytest.approx(march.revenue.sum() - february.revenue.sum())
    assert result.findings.sample_sizes.model_dump() == {"current": len(march), "baseline": len(february)}


def test_zero_baseline_has_no_percentage() -> None:
    frame = pd.DataFrame({"order_date": pd.to_datetime(["2025-01-05", "2025-02-05"]), "revenue": [0.0, 10.0]})
    request = compare_request(
        period=window("February", "2025-02-01", "2025-03-01"),
        baseline=window("January", "2025-01-01", "2025-02-01"),
    )
    findings = period_compare(frame, request).findings
    assert findings.change.percentage is None
    assert any("baseline value is zero" in warning for warning in findings.warnings)


def test_missing_period_is_reported(sales: pd.DataFrame) -> None:
    request = compare_request(period=window("January 2030", "2030-01-01", "2030-02-01"))
    findings = period_compare(sales, request).findings
    assert findings.values.current == 0
    assert findings.sample_sizes.current == 0
    assert any("No rows" in warning for warning in findings.warnings)


def test_contribution_deltas_and_ranking(sales: pd.DataFrame) -> None:
    result = contribution(sales, contribution_request())
    assert sum(item.delta for item in result.findings.ranked_contributors) == pytest.approx(result.findings.change.absolute)
    magnitudes = [abs(item.delta) for item in result.findings.ranked_contributors]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert result.viz["type"] == "bar"


def test_thin_segments_are_warned() -> None:
    frame = pd.DataFrame({
        "order_date": pd.to_datetime(["2025-01-05", "2025-02-05"]),
        "revenue": [4.0, 9.0],
        "region": ["North", "North"],
    })
    findings = contribution(frame, contribution_request()).findings
    assert any("Thin segment 'North'" in warning for warning in findings.warnings)


@pytest.mark.parametrize("metric", ["missing", "region"])
def test_unknown_or_non_numeric_metric_is_rejected(sales: pd.DataFrame, metric: str) -> None:
    with pytest.raises(AnalysisValidationError):
        run_analysis(sales, compare_request(metric=metric))


def test_unknown_dimension_is_rejected(sales: pd.DataFrame) -> None:
    with pytest.raises(AnalysisValidationError, match="Unknown dimension"):
        contribution(sales, contribution_request("missing"))


def test_bad_period_and_unknown_tool_are_rejected() -> None:
    bad_period = compare_request().model_dump(mode="json")
    bad_period["params"]["period"]["start"] = "March"
    with pytest.raises(ValidationError):
        ANALYSIS_REQUEST_ADAPTER.validate_python(bad_period)
    with pytest.raises(ValidationError):
        ANALYSIS_REQUEST_ADAPTER.validate_python({"mode": "analysis", "tool": "system", "params": {}})


def test_findings_schema_forbids_unexpected_fields(sales: pd.DataFrame) -> None:
    payload = period_compare(sales, compare_request()).findings.model_dump(mode="json")
    payload["invented"] = 42
    with pytest.raises(ValidationError):
        Findings.model_validate(payload)
