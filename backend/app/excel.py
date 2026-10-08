"""Excel-only validation and parsing; the CSV path remains independent."""
from __future__ import annotations

from datetime import time, timedelta
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree
from zipfile import ZipFile

import pandas as pd
from fastapi import Request
from fastapi.responses import JSONResponse

from .datasets import (
    MAX_UPLOAD_BYTES, MAX_UPLOAD_COLUMNS, MAX_UPLOAD_ROWS, DatasetError,
)


MAX_WORKBOOK_SHEETS = 10
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
# pandas builds a rectangular array before dropping empty rows/columns. Guard
# sparse cell coordinates as well as the final, cleaned dataset dimensions.
MAX_SOURCE_ROWS = 200_000
MAX_SOURCE_COLUMNS = 1_000
MAX_SOURCE_CELLS = (MAX_UPLOAD_ROWS + 1) * MAX_UPLOAD_COLUMNS
EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}
UNSUPPORTED_EXCEL = "Only .xlsx files are supported. Save the file as .xlsx and try again."
ENGINE_OPTIONS = {"read_only": True, "data_only": True, "keep_links": False, "keep_vba": False}


def _validate_archive(content: bytes) -> None:
    with ZipFile(BytesIO(content)) as archive:
        entries = archive.infolist()
        if sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
            raise DatasetError("The workbook exceeds the 100 MB uncompressed size limit.")
        if any(PurePosixPath(entry.filename).name.lower() == "vbaproject.bin" for entry in entries):
            raise DatasetError(UNSUPPORTED_EXCEL)
        total = 0
        for entry in entries:
            tail = b""
            with archive.open(entry) as source:
                while chunk := source.read(64 * 1024):
                    total += len(chunk)
                    if total > MAX_UNCOMPRESSED_BYTES:
                        raise DatasetError("The workbook exceeds the 100 MB uncompressed size limit.")
                    # Refuse XML entity declarations before the Excel engine sees
                    # them. Removing NULs also covers UTF-16/UTF-32 XML encodings.
                    if entry.filename.lower().endswith((".xml", ".rels")):
                        scan = (tail + chunk).replace(b"\x00", b"").upper()
                        if b"<!DOCTYPE" in scan or b"<!ENTITY" in scan:
                            raise DatasetError("The workbook contains unsupported XML declarations.")
                        tail = (tail + chunk)[-64:]
                    if entry.filename == "[Content_Types].xml" and b"macroenabled" in (tail + chunk).lower():
                        raise DatasetError(UNSUPPORTED_EXCEL)
        for entry in entries:
            if entry.filename.startswith("xl/worksheets/") and entry.filename.endswith(".xml"):
                max_row = max_column = 0
                with archive.open(entry) as source:
                    for _, element in ElementTree.iterparse(source, events=("end",)):
                        if element.tag.rsplit("}", 1)[-1] == "c":
                            coordinate = element.get("r", "")
                            letters = coordinate.rstrip("0123456789")
                            digits = coordinate[len(letters):]
                            column = 0
                            for letter in letters:
                                column = column * 26 + ord(letter) - ord("A") + 1
                            max_column = max(max_column, column)
                            max_row = max(max_row, int(digits) if digits else 0)
                            if (max_row > MAX_SOURCE_ROWS or max_column > MAX_SOURCE_COLUMNS
                                    or max_row * max_column > MAX_SOURCE_CELLS):
                                raise DatasetError("A worksheet is too sparse or large to parse safely. Remove distant empty cells and try again.")
                        element.clear()


def _excel_value(value: object) -> object:
    # Native Excel times/durations are Python objects that the shared JSON
    # serializer does not accept. Preserve them as text before type inference;
    # named time columns then follow the existing CSV date conversion rule.
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return pd.Timedelta(value).isoformat()
    return value


def _sheet_frame(raw: pd.DataFrame, sheet: str) -> pd.DataFrame | None:
    # Preserve literal text such as "NA" in headers and cells. Only genuinely
    # empty or whitespace-only cells count as empty for workbook cleanup.
    raw = raw.replace(r"^\s*$", float("nan"), regex=True)
    raw = raw.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if raw.empty:
        return None
    if len(raw.columns) > MAX_UPLOAD_COLUMNS:
        raise DatasetError(f'Sheet "{sheet}" exceeds the 100-column limit.')
    if len(raw) - 1 > MAX_UPLOAD_ROWS:
        raise DatasetError(f'Sheet "{sheet}" exceeds the 100,000-row limit.')
    header = raw.iloc[0]
    names = ["" if pd.isna(value) else str(value).strip() for value in header]
    if (any(not name or name.lower().startswith("unnamed:") for name in names)
            or len(names) != len(set(names))
            or not any(isinstance(value, str) for value in header)):
        raise DatasetError(f'Sheet "{sheet}" must have a header row with non-empty, unique column names.')
    frame = raw.iloc[1:].reset_index(drop=True).copy()
    frame.columns = names
    # Removing the header allows pandas to infer numbers and native Excel dates.
    frame = frame.map(_excel_value).infer_objects()
    for column in frame.columns:
        series = frame[column]
        normalized = column.lower()
        if pd.api.types.is_datetime64_any_dtype(series.dtype):
            # CSV pd.to_datetime uses microseconds in our pinned pandas version.
            frame[column] = series.astype("datetime64[us]")
        elif pd.api.types.is_string_dtype(series.dtype) and (
            "date" in normalized or "time" in normalized or normalized.endswith("_at")
        ):
            converted = pd.to_datetime(series, errors="coerce")
            if series.notna().sum() and converted.notna().sum() == series.notna().sum():
                frame[column] = converted
    return frame


def parse_xlsx(content: bytes) -> list[tuple[str, pd.DataFrame]]:
    if not content:
        raise DatasetError("The uploaded workbook is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DatasetError("The workbook exceeds the 10 MB upload limit.")
    try:
        _validate_archive(content)
        with pd.ExcelFile(BytesIO(content), engine="openpyxl", engine_kwargs=ENGINE_OPTIONS) as workbook:
            if len(workbook.sheet_names) > MAX_WORKBOOK_SHEETS:
                raise DatasetError("The workbook exceeds the 10-sheet limit.")
            sheets = []
            for name in workbook.sheet_names:
                raw = pd.read_excel(workbook, sheet_name=name, header=None, keep_default_na=False)
                frame = _sheet_frame(raw, name)
                if frame is not None:
                    sheets.append((name, frame))
            if not sheets:
                raise DatasetError("The workbook has no non-empty sheets.")
            return sheets
    except DatasetError:
        raise
    except Exception as exc:
        raise DatasetError("The file could not be parsed as an .xlsx workbook.") from exc


async def upload_excel(request: Request, filename: str) -> JSONResponse:
    if PurePosixPath(filename.lower()).suffix != ".xlsx":
        return JSONResponse(status_code=400, content={"error": UNSUPPORTED_EXCEL})
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_UPLOAD_BYTES:
            return JSONResponse(status_code=413, content={"error": "The workbook exceeds the 10 MB upload limit."})
    try:
        registry = request.app.state.datasets
        sheets = registry.add_excel_upload(filename, bytes(content))
        response = registry.summary(sheets[0])
        if len(sheets) > 1:
            response["datasets"] = [{"dataset_id": sheet.dataset_id, "name": sheet.name} for sheet in sheets]
        return JSONResponse(status_code=201, content=response)
    except DatasetError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
