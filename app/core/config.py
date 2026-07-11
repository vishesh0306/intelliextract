from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://intelliextract:intelliextract@localhost:5432/intelliextract"
    )
    redis_url: str = "redis://localhost:6379/0"

    storage_backend: str = "local"  # "local" or "s3"
    local_storage_path: str = "storage"
    max_upload_size_mb: int = 20
    s3_bucket_name: str | None = None
    aws_region: str | None = None

    # Only needed on hosts where tesseract isn't on PATH (e.g. Windows dev
    # boxes); the Docker image installs it via apt and needs no override.
    tesseract_cmd: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
