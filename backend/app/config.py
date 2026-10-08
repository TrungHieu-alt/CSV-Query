from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8")


def _origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_backup_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_BACKUP_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"))
    gemini_fallback_model: str = field(default_factory=lambda: os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash"))
    allowed_origins: list[str] = field(default_factory=_origins)
    csv_path: Path = field(default_factory=lambda: Path(os.getenv("CSV_PATH", str(PROJECT_ROOT / "backend" / "data" / "sales_data.csv"))))
    rate_limit_per_minute: int = 20
