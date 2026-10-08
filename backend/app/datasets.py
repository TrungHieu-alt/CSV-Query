from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from threading import Lock
from typing import Any
from uuid import uuid4

import pandas as pd

from .executor import dataframe_page
from .schema import build_schema, example_questions


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_ROWS = 100_000
MAX_UPLOAD_COLUMNS = 100


class DatasetError(ValueError):
    """A safe validation error for an uploaded dataset."""


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    name: str
    frame: pd.DataFrame
    schema: list[dict[str, Any]]
    examples: list[str]


def parse_csv(content: bytes) -> pd.DataFrame:
    if not content:
        raise DatasetError("The uploaded CSV is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DatasetError("The CSV exceeds the 10 MB upload limit.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetError("The CSV must use UTF-8 encoding.") from exc
    try:
        frame = pd.read_csv(StringIO(text))
    except Exception as exc:
        raise DatasetError("The file could not be parsed as CSV.") from exc
    if frame.columns.empty:
        raise DatasetError("The CSV must contain a header row.")
    if len(frame.columns) > MAX_UPLOAD_COLUMNS:
        raise DatasetError("The CSV exceeds the 100-column limit.")
    if len(frame) > MAX_UPLOAD_ROWS:
        raise DatasetError("The CSV exceeds the 100,000-row limit.")

    columns = [str(column).strip() for column in frame.columns]
    if any(not column for column in columns) or len(columns) != len(set(columns)):
        raise DatasetError("Column names must be non-empty and unique.")
    frame.columns = columns

    for column in frame.columns:
        normalized = column.lower()
        if pd.api.types.is_string_dtype(frame[column].dtype) and (
            "date" in normalized or "time" in normalized or normalized.endswith("_at")
        ):
            converted = pd.to_datetime(frame[column], errors="coerce")
            if frame[column].notna().sum() and converted.notna().sum() == frame[column].notna().sum():
                frame[column] = converted
    return frame


class DatasetRegistry:
    def __init__(self, default_frame: pd.DataFrame, service_builder: Any) -> None:
        self._service_builder = service_builder
        self._datasets: dict[str, Dataset] = {}
        self._services: dict[str, Any] = {}
        self._lock = Lock()
        self._add("default", "Bundled sales data", default_frame)

    def _add(self, dataset_id: str, name: str, frame: pd.DataFrame) -> Dataset:
        schema = build_schema(frame)
        dataset = Dataset(dataset_id, name, frame, schema, example_questions(schema))
        self._datasets[dataset_id] = dataset
        self._services[dataset_id] = self._service_builder(frame, schema)
        return dataset

    def add_upload(self, name: str, content: bytes) -> Dataset:
        frame = parse_csv(content)
        safe_name = name.strip()[:120] or "Uploaded CSV"
        with self._lock:
            return self._add(uuid4().hex, safe_name, frame)

    def add_excel_upload(self, name: str, content: bytes) -> list[Dataset]:
        from .excel import parse_xlsx

        sheets = parse_xlsx(content)
        safe_name = name.strip()[:120] or "Uploaded workbook"
        with self._lock:
            return [self._add(uuid4().hex, f"{safe_name} – {sheet}", frame) for sheet, frame in sheets]

    def get(self, dataset_id: str) -> Dataset:
        with self._lock:
            dataset = self._datasets.get(dataset_id)
        if dataset is None:
            raise DatasetError("Dataset not found. Upload the file again.")
        return dataset

    def get_service(self, dataset_id: str) -> Any:
        self.get(dataset_id)
        with self._lock:
            return self._services[dataset_id]

    @staticmethod
    def summary(dataset: Dataset, preview_limit: int = 20) -> dict[str, Any]:
        page = dataframe_page(dataset.frame, 0, preview_limit)
        return {
            "dataset_id": dataset.dataset_id,
            "name": dataset.name,
            "columns": dataset.schema,
            "column_names": page.columns,
            "rows": page.rows,
            "row_count": page.row_count,
        }

