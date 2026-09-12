from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path(__file__).resolve().parents[2] / "data"
    max_upload_bytes: int = 15000 * 1024 * 1024
    max_extract_files: int = 10000
    max_extract_bytes: int = 500000 * 1024 * 1024
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-5-mini"
    # fake | local | openai（預設 local 方便離線；部署請用 .env）
    embedding_backend: str = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    # openai embedding 專用（例如 OpenRouter）；未設則回退 OPENAI_*
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    use_fake_llm: bool = False


def get_settings() -> Settings:
    return Settings()
