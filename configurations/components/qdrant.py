from pydantic import BaseModel


class QdrantConfig(BaseModel):
    host: str = "localhost"
    port: int = 6333
    api_key: str | None = None
    https: bool = False
