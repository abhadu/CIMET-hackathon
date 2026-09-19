from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "QA Gate"
    database_url: str = "sqlite:///./qa_gate.db"
    storage_dir: Path = Path("./storage")
    frontend_dist: Path = Path("./frontend/dist")

    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1"

    deepgram_api_key: str | None = None
    deepgram_model: str = "nova-3"

    qa_sample_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    min_confidence: float = 0.75
    dead_air_threshold_s: float = 20.0
    repeat_offence_threshold: int = 3
    repeat_offence_window_days: int = 7


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings
