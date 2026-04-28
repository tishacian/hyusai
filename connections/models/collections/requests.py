from pydantic import BaseModel, Field


class CreateCollectionPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=2048)


class PatchCollectionPayload(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2048)
