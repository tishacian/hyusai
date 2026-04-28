import asyncio
import logging
import pickle

from connections.celery.task_response import TaskResponse
from connections.database.chats import Chats
from connections.database.system_prompts import SystemPrompts
from connections.database.users import Users
from connections.models.flow_operations.query_llm_pipeline.payload import QueryPayload
from connections.qdrant import qdrant_client
from connections.storage import WORKSPACE_UUID, fs
from src.services.llm import create_llm_service

logger = logging.getLogger(__name__)

# Sentinel user_id used when no authenticated user is available.
# Will be replaced once Keycloak integration lands.
_DEV_USER_EMAIL = "dev"


def _resolve_user_id() -> int | None:
    """Return the dev user's DB id, or None if it cannot be resolved."""
    try:
        user = Users.get_by_email(_DEV_USER_EMAIL)
        return user.id if user else None
    except Exception as exc:
        logger.warning("Could not resolve user_id for chat persistence: %s", exc)
        return None


class RAGOrchestrationService:
    """Orchestrates retrieval + generation for a single RAG query turn."""

    def call(self, payload: QueryPayload) -> TaskResponse:
        return asyncio.run(self._call_async(payload))

    async def _call_async(self, payload: QueryPayload) -> TaskResponse:
        from sentence_transformers import SentenceTransformer

        kb_uuid = str(payload.collection_uuid)
        k = payload.retrieval.top_k

        # 1. Encode query into a dense vector
        embedding_model = SentenceTransformer(payload.retrieval.embedding_model_name)
        query_vector = embedding_model.encode(payload.user_prompt).tolist()

        # 2. Dense vector search against Qdrant
        vector_hits = qdrant_client.search(
            collection_name=kb_uuid,
            query_vector=query_vector,
            limit=k,
        )
        vector_texts = [hit.payload.get("text", "") for hit in vector_hits]

        # 3. BM25 keyword search — load index stored at the path in point payloads
        bm25_path_relative = (
            vector_hits[0].payload.get("bm25_path") if vector_hits else None
        )
        bm25_texts: list[str] = []
        if bm25_path_relative:
            try:
                bm25_abs_path = fs.joinpath(WORKSPACE_UUID, bm25_path_relative)
                bm25_retriever = fs.loader(bm25_abs_path, pickle.load)
                tokenized_query = payload.user_prompt.lower().split()
                bm25_texts = bm25_retriever.get_top_n(
                    tokenized_query, bm25_retriever.corpus, n=k
                )
            except Exception as exc:
                logger.warning(
                    "BM25 retrieval failed, falling back to vector-only: %s", exc
                )

        # 4. Merge and deduplicate by content hash, preserving insertion order
        seen: set[int] = set()
        contexts: list[str] = []
        for text in vector_texts + bm25_texts:
            h = hash(text)
            if h not in seen and text:
                seen.add(h)
                contexts.append(text)
        contexts = contexts[:k]

        # 5. Fetch system prompt from DB
        system_prompt_record = SystemPrompts.get_by_language(
            payload.generation.system_prompt_language
        )
        system_prompt = (
            system_prompt_record.llm_role_definition
            if system_prompt_record
            else "You are a helpful assistant."
        )

        # 6. Build the RAG prompt
        context_block = "\n\n".join(
            f"Context {i + 1}:\n{c}" for i, c in enumerate(contexts)
        )
        prompt = (
            f"{context_block}\n\n"
            f"Question: {payload.user_prompt}\n\n"
            f"Answer based on the context above:"
        )

        # 7. Generate with the configured LLM service
        llm = create_llm_service(payload.generation)
        answer = await llm.generate(prompt, system_prompt)

        # 8. Persist the chat turn
        chat_id = self._save_chat(payload, answer)

        return {
            "status": "success",
            "answer": answer,
            "context": contexts,
            "chat_history_id": chat_id,
        }

    def _save_chat(self, payload: QueryPayload, answer: str) -> int | None:
        """Persist the new turn to the Chats table. Returns the chat ID, or None on failure."""
        user_id = _resolve_user_id()
        if user_id is None:
            logger.warning(
                "Skipping chat persistence: no user_id available. "
                "Integrate Keycloak to enable per-user chat history."
            )
            return None

        try:
            # Load existing history or start a new conversation
            if payload.chat_history_id is not None:
                existing_history, *_ = Chats.get_chat(payload.chat_history_id)
            else:
                existing_history = []

            history = list(existing_history)
            history.append({"role": "human", "content": payload.user_prompt})
            history.append({"role": "ai", "content": answer})

            if payload.chat_history_id is not None:
                # Update the existing chat entry in-place
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
            else:
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
