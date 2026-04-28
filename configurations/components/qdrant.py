from pydantic_settings import BaseSettings, SettingsConfigDict


class QdrantConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QDRANT_")

    host: str = "localhost"
    port: int = 6333
    api_key: str | None = None
    https: bool = False
