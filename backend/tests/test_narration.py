from backend.app.analysis import Findings
from backend.app.narration import Narration, fallback_narration, grounded_or_fallback, narration_is_grounded


def findings() -> Findings:
    return Findings.model_validate({
        "tool": "period_compare",
        "metric": "revenue",
        "date_column": "order_date",
        "period": {"label": "March 2025", "start": "2025-03-01", "end": "2025-04-01"},
        "baseline": {"label": "February 2025", "start": "2025-02-01", "end": "2025-03-01"},
        "grain": "month",
        "dimension": None,
        "values": {"current": 120.0, "baseline": 100.0},
        "change": {"absolute": 20.0, "percentage": 20.0},
        "ranked_contributors": [],
        "sample_sizes": {"current": 12, "baseline": 10},
        "warnings": [],
    })


def test_grounded_narration_is_kept() -> None:
    narration = Narration(headline="Revenue increased 20.0% in March 2025.", insights=["The comparison used 12 and 10 rows."])
    assert narration_is_grounded(narration, findings()) is True
    assert grounded_or_fallback(narration, findings()) == narration


def test_invented_number_uses_deterministic_fallback(caplog) -> None:
    invented = Narration(headline="Revenue increased 99%.", insights=[])
    result = grounded_or_fallback(invented, findings())
    assert result == fallback_narration(findings())
    assert "not present in FINDINGS" in caplog.text
    assert "99" not in result.headline


def test_rounding_tolerance_accepts_display_rounding() -> None:
    narration = Narration(headline="Revenue reached 120 in March 2025.", insights=[])
    assert narration_is_grounded(narration, findings()) is True
