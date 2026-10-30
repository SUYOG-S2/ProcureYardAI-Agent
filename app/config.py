from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str
    payswift_base_url: str = "http://localhost:8081"
    timezone: str = "Asia/Kolkata"
    openrouter_api_key: str
    openrouter_model: str
    mem0_api_key: str
    pinecone_api_key: str
    pinecone_index_name: str
    embedding_model: str = "text-embedding-3-small"
    data_dir: str = "data"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()