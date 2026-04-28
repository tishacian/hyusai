from fastapi import APIRouter, HTTPException, status

from connections.database.chats import Chats
from connections.database.users import Users
from connections.models.db.requests import ChatCreateRequest, ChatUpdateRequest
from connections.models.db.responses import (
    ChatCreateResponse,
    ChatDeleteResponse,
    ChatDetailResponse,
    ChatListItem,
)

router = APIRouter()


def _get_user_or_404(username: str):
    user = Users.get_by_email(username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User not found: {username}",
        )
    return user


def _get_chat_or_404(chat_id: int) -> tuple:
    result = Chats.get_chat(chat_id)
    chat_history = result[0]
    if not chat_history and all(v is None for v in result[1:]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chat not found: {chat_id}",
        )
    return result


@router.get("/chats", response_model=list[ChatListItem])
async def list_chats(username: str):
    """Return all chats for a user, ordered by timestamp descending."""
    user = _get_user_or_404(username)
    rows = Chats.get_all_user_chats(user.id)
    return [ChatListItem(chat_id=row[0], timestamp=row[1]) for row in rows]


@router.get("/chats/{chat_id}", response_model=ChatDetailResponse)
async def get_chat(chat_id: int):
    """Return full chat history and metadata for a single chat."""
    (
        chat_history,
        model_name,
        chunking_method,
        index_type,
        vector_store,
        pipeline_type,
        instruction_lang,
    ) = _get_chat_or_404(chat_id)
    return ChatDetailResponse(
        chat_id=chat_id,
        chat_history=chat_history,
        model_name=model_name,
        chunking_method=chunking_method,
        index_type=index_type,
        vector_store=vector_store,
        pipeline_type=pipeline_type,
        instruction_lang=instruction_lang,
    )


@router.post(
    "/chats", status_code=status.HTTP_201_CREATED, response_model=ChatCreateResponse
)
async def create_chat(body: ChatCreateRequest):
    """Create a new chat entry and return the new chat ID."""
    user = _get_user_or_404(body.username)
    chat_id = Chats.post_chat(
        user_id=user.id,
        chat_history=body.chat_history,
        model_name=body.model_name,
        chunking_method=body.chunking_method,
        index_type=body.index_type,
        vector_store=body.vector_store,
        pipeline_type=body.pipeline_type,
        instruction_lang=body.instruction_lang,
    )
    return ChatCreateResponse(chat_id=chat_id)


@router.put("/chats/{chat_id}", response_model=ChatDetailResponse)
async def update_chat(chat_id: int, body: ChatUpdateRequest):
    """Update an existing chat entry."""
    _get_chat_or_404(chat_id)
    Chats.update_chat(
        chat_id,
        chat_history=body.chat_history,
        model_name=body.model_name,
        chunking_method=body.chunking_method,
        index_type=body.index_type,
        vector_store=body.vector_store,
        pipeline_type=body.pipeline_type,
        instruction_lang=body.instruction_lang,
    )
    return ChatDetailResponse(
        chat_id=chat_id,
        chat_history=body.chat_history,
        model_name=body.model_name,
        chunking_method=body.chunking_method,
        index_type=body.index_type,
        vector_store=body.vector_store,
        pipeline_type=body.pipeline_type,
        instruction_lang=body.instruction_lang,
    )


@router.delete("/chats/{chat_id}", response_model=ChatDeleteResponse)
async def delete_chat(chat_id: int):
    """Delete a single chat entry."""
    _get_chat_or_404(chat_id)
    Chats.delete_chat(chat_id)
    return ChatDeleteResponse(chat_id=chat_id, deleted=True)


@router.delete("/chats", response_model=ChatDeleteResponse)
async def delete_all_user_chats(username: str):
    """Delete all chats for a user. Idempotent — returns 0 if there are none."""
    user = _get_user_or_404(username)
    existing = Chats.get_all_user_chats(user.id)
    count = len(existing)
    Chats.delete_all_user_chats(user.id)
    return ChatDeleteResponse(deleted=True, deleted_count=count)
