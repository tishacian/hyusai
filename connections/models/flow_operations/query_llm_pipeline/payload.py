from uuid import UUID

from pydantic import BaseModel, Field

from .generation_config import GenerationConfig
from .retrieval_config import RetrievalConfig


class QueryPayload(BaseModel):
    collection_uuid: UUID = Field(
        ...,
        description="UUID of the collection to retrieve context from.",
    )
    user_prompt: str = Field(
        ...,
        description="User's question or instruction to the RAG pipeline.",
    )
    chat_history_id: int | None = Field(
        None,
        description=(
            "ID of an existing chat session to continue. "
            "None starts a new conversation. "
            "When provided, prior turns are prepended to the prompt for context."
        ),
    )
    retrieval: RetrievalConfig = Field(
        default_factory=RetrievalConfig,
        description="Retrieval strategy and parameters controlling how document chunks are fetched.",
    )
    generation: GenerationConfig = Field(
        default_factory=GenerationConfig,
        description="LLM provider and generation parameters controlling answer synthesis.",
    )


# Backward-compat alias for Celery task dispatch
QueryLLMPipelinePayload = QueryPayload
