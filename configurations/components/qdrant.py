from pydantic import BaseModel


class QdrantConfig(BaseModel):
    host: str = "qdrant"
    port: int = 6333
    api_key: str | None = None
