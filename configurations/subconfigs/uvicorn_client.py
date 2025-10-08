from pydantic_settings import BaseSettings


class UvicornClientConfig(BaseSettings):
    host: str = "fastapi"
    port: int = 8000
    protocol: str = "http"

    @property
    def url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"
