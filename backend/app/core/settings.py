from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str | None = None
    tavily_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    search_provider: Literal["tavily", "fixture"] = "tavily"
    llm_provider: Literal["openai", "fixture"] = "openai"
    backend_base_url: str = "http://127.0.0.1:8000"
    data_dir: Path = Path("data")


@lru_cache
def get_settings() -> Settings:
    return Settings()

