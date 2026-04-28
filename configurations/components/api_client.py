from pydantic_settings import BaseSettings, SettingsConfigDict


class APIClientConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="API_")

    host: str = "fastapi"
    port: int = 8000
    protocol: str = "http"

    @property
    def url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"
