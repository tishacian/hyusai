from pydantic import BaseModel


class FastAPIClientConfig(BaseModel):
    host: str = "fastapi"
    port: int = 8000
    protocol: str = "http"

    @property
    def url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"
