import asyncio
import logging
from collections.abc import AsyncIterable

from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent

from connections.celery.tasks import retrieve_rag_context
from connections.database.chats import Chats
from connections.database.users import Users
from connections.models.flow_operations.query_llm_pipeline.generation_config import (
    OPENAI_REASONING_MODELS,
)
from connections.models.flow_operations.query_llm_pipeline.payload import QueryPayload
from connections.openai_client import openai_client

router = APIRouter()
logger = logging.getLogger(__name__)

_DEV_USER_EMAIL = "dev"


def _resolve_user_id() -> int | None:
    try:
        user = Users.get_by_email(_DEV_USER_EMAIL)
        return user.id if user else None
    except Exception as exc:
        logger.warning("Could not resolve user_id: %s", exc)
        return None


def _save_chat(payload: QueryPayload, answer: str, contexts: list[str]) -> int | None:
    user_id = _resolve_user_id()
    if user_id is None:
        return None
    try:
        if payload.chat_history_id is not None:
            existing_history, *meta = Chats.get_chat(payload.chat_history_id)
            chat_exists = any(v is not None for v in meta)
        else:
            existing_history = []
            chat_exists = False
        history = list(existing_history)
        history.append({"role": "human", "content": payload.user_prompt})
        history.append({"role": "ai", "content": answer})
        if payload.chat_history_id is not None and chat_exists:
            Chats.update_chat(
                payload.chat_history_id,
                chat_history=history,
                model_name=payload.generation.model_name,
                chunking_method=None,
                index_type=None,
                vector_store=str(payload.collection_uuid),
                pipeline_type=payload.retrieval.strategy,
                instruction_lang=payload.generation.system_prompt_language,
            )
            return payload.chat_history_id
        return Chats.post_chat(
            user_id=user_id,
            chat_history=history,
            model_name=payload.generation.model_name,
            chunking_method=None,
            index_type=None,
            vector_store=str(payload.collection_uuid),
            pipeline_type=payload.retrieval.strategy,
            instruction_lang=payload.generation.system_prompt_language,
        )
    except Exception as exc:
        logger.warning("Failed to persist chat turn: %s", exc)
        return None


@router.post("/stream", response_class=EventSourceResponse)
async def query_stream(payload: QueryPayload) -> AsyncIterable[ServerSentEvent]:
    """Stream a RAG query response via Server-Sent Events.

    Dispatches retrieval to a Celery worker (encoding, vector + BM25 search,
    context assembly), then streams OpenAI completion tokens back to the client.

    SSE event protocol::

        event: retrieval_done   data: {"task_id": "<id>"}
        event: token            data: {"content": "<partial text>"}
        event: done             data: {"chat_id": int, "answer": str, "context": [str]}
        event: error            data: {"message": "<description>"}
    """
    # 1. Dispatch retrieval to Celery cpu queue
    task = retrieve_rag_context.apply_async(
        args=(payload.model_dump(mode="json"),), queue="cpu"
    )
    yield ServerSentEvent(data={"task_id": task.id}, event="retrieval_done")

    # 2. Await retrieval result without blocking the event loop
    loop = asyncio.get_event_loop()
    try:
        retrieval = await asyncio.wait_for(
            loop.run_in_executor(None, task.get),
            timeout=120.0,
        )
    except TimeoutError:
        yield ServerSentEvent(data={"message": "retrieval timed out"}, event="error")
        return
    except Exception as exc:
        yield ServerSentEvent(data={"message": str(exc)}, event="error")
        return

    # 3. Stream OpenAI completion
    # Build structured input: RAG context as a developer message (higher authority
    # than user, clearly separated from the question), preceded by any prior
    # conversation turns so the model has multi-turn context.
    input_messages: list[dict] = [
        {
            "role": "developer",
            "content": f"Retrieved context:\n{retrieval['combined_context']}",
        },
    ]
    if payload.chat_history_id is not None:
        try:
            history, *_ = Chats.get_chat(payload.chat_history_id)
            for turn in history or []:
                role = "user" if turn["role"] == "human" else "assistant"
                input_messages.append({"role": role, "content": turn["content"]})
        except Exception as exc:
            logger.warning(
                "Could not load chat history %s: %s", payload.chat_history_id, exc
            )
    input_messages.append({"role": "user", "content": payload.user_prompt})

    full_answer = ""
    try:
        kwargs: dict = dict(
            model=payload.generation.model_name,
            instructions=retrieval["system_prompt"],
            input=input_messages,
            temperature=payload.generation.temperature,
            max_output_tokens=payload.generation.max_tokens,
            store=False,
        )
        if payload.generation.model_name in OPENAI_REASONING_MODELS:
            kwargs["include"] = ["reasoning.encrypted_content"]
        if payload.generation.top_p is not None:
            kwargs["top_p"] = payload.generation.top_p

        async with openai_client.responses.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "response.output_text.delta":
                    token = event.delta
                    if token:
                        full_answer += token
                        yield ServerSentEvent(data={"content": token}, event="token")
    except Exception as exc:
        logger.error("OpenAI streaming error: %s", exc)
        yield ServerSentEvent(data={"message": str(exc)}, event="error")
        return

    # 4. Persist chat and emit done
    chat_id = _save_chat(payload, full_answer, retrieval.get("contexts", []))
    yield ServerSentEvent(
        data={
            "chat_id": chat_id,
            "answer": full_answer,
            "context": retrieval.get("contexts", []),
        },
        event="done",
    )
