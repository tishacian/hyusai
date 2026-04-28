from datetime import datetime

from pydantic import BaseModel


class ChatListItem(BaseModel):
    chat_id: int
    timestamp: datetime | None = None


class ChatDetailResponse(BaseModel):
    chat_id: int
    chat_history: list[dict]
    model_name: str | None = None
    chunking_method: str | None = None
    index_type: str | None = None
    vector_store: str | None = None
    pipeline_type: str | None = None
    instruction_lang: str | None = None


class ChatCreateResponse(BaseModel):
    chat_id: int


class ChatDeleteResponse(BaseModel):
    chat_id: int | None = None
    deleted: bool
    deleted_count: int | None = None


class UserItem(BaseModel):
    email: str
    name: str
