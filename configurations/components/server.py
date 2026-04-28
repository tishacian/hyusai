from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SERVER_")

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str | None = None
    access_log: bool = False
    log_config: dict | None = None
