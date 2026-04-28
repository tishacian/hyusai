from pydantic import BaseModel


class ChatCreateRequest(BaseModel):
    username: str
    chat_history: list[dict]
    model_name: str | None = None
    chunking_method: str | None = None
    index_type: str | None = None
    vector_store: str | None = None
    pipeline_type: str | None = None
    instruction_lang: str | None = None


class ChatUpdateRequest(BaseModel):
    chat_history: list[dict]
    model_name: str | None = None
    chunking_method: str | None = None
    index_type: str | None = None
    vector_store: str | None = None
    pipeline_type: str | None = None
    instruction_lang: str | None = None


class UserCreateRequest(BaseModel):
    email: str
    password: str
    name: str
    role: str = "user"


class UserVerifyRequest(BaseModel):
    email: str
    password: str
