from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Document OCR API"
    allowed_origins: list[str] = ["http://localhost:5173"]
    max_upload_bytes: int = 10 * 1024 * 1024
    max_pdf_pages: int = 10
    data_dir: Path = Path(__file__).resolve().parents[1] / "data"


@lru_cache
def get_settings() -> Settings:
    return Settings()
