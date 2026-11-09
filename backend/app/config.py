from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Document OCR API"
    allowed_origins: list[str] = ["http://localhost:5173"]
    max_upload_bytes: int = 10 * 1024 * 1024
    max_pdf_pages: int = 10
    session_ttl_seconds: int = 60 * 60
    session_cleanup_interval_seconds: int = 5 * 60
    max_session_forms: int = 5
    max_session_storage_bytes: int = 40 * 1024 * 1024
    max_session_creations_per_minute: int = 30
    max_ocr_requests_per_minute: int = 20
    max_ocr_requests_per_session_per_minute: int = 6
    max_concurrent_ocr_jobs: int = 1
    data_dir: Path = Path(__file__).resolve().parents[1] / "data"


@lru_cache
def get_settings() -> Settings:
    return Settings()
