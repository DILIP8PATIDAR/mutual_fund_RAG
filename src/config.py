"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: str = Field(default="", description="Groq API key")
    llm_model: str = Field(default="llama-3.3-70b-versatile")
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    vector_db_path: Path = Field(default=PROJECT_ROOT / "data" / "chroma")
    top_k: int = Field(default=5, ge=1)
    similarity_threshold: float = Field(default=0.65, ge=0.0, le=1.0)

    # LLM generation + Groq free-tier rate-limit controls
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=256, ge=1)
    llm_context_char_budget: int = Field(default=6000, ge=500)
    groq_max_retries: int = Field(default=3, ge=0)
    groq_timeout_sec: float = Field(default=30.0, gt=0.0)

    urls_file: Path = Field(default=PROJECT_ROOT / "data" / "urls.json")
    raw_data_dir: Path = Field(default=PROJECT_ROOT / "data" / "raw")
    processed_data_dir: Path = Field(default=PROJECT_ROOT / "data" / "processed")

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
