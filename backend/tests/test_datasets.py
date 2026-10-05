import pandas as pd
import pytest

from backend.app.datasets import DatasetError, parse_csv
from backend.app.executor import dataframe_page


def test_parse_csv_infers_named_dates() -> None:
    frame = parse_csv(b"event_date,value\n2026-01-01,3\n2026-01-02,4\n")
    assert pd.api.types.is_datetime64_any_dtype(frame["event_date"])
    assert frame["value"].sum() == 7


def test_parse_csv_keeps_non_date_text() -> None:
    frame = parse_csv(b"name,note\nAda,hello\nLin,world\n")
    assert list(frame.columns) == ["name", "note"]
    assert frame.iloc[0]["name"] == "Ada"


@pytest.mark.parametrize("content", [b"", b"\xff", b"\n"])
def test_parse_csv_rejects_invalid_content(content: bytes) -> None:
    with pytest.raises(DatasetError):
        parse_csv(content)


def test_dataframe_page_is_json_safe_and_paginated() -> None:
    frame = pd.DataFrame({"when": pd.to_datetime(["2026-01-01", "2026-01-02"]), "value": [1, 2]})
    result = dataframe_page(frame, offset=1, limit=1)
    assert result.rows == [{"when": "2026-01-02T00:00:00", "value": 2}]
    assert result.row_count == 2
    assert result.truncated is False
