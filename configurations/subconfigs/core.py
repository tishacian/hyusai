from pydantic import BaseModel


class CoreConfig(BaseModel):
    host: str = "http://core:8000"
