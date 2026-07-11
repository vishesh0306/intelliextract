from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://intelliextract:intelliextract@localhost:5432/intelliextract"
    )
    redis_url: str = "redis://localhost:6379/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
