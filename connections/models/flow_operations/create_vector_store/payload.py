from uuid import UUID

from pydantic import BaseModel, Field

from .components.chunking_params import ChunkingParams
from .components.embedding_params import EmbeddingConfig


class IndexCollectionPayload(BaseModel):
    collection_uuid: UUID = Field(
        ...,
        description="UUID of the collection to index.",
    )
    chunking: ChunkingParams = Field(
        ...,
        description="Text chunking strategy and method-specific parameters.",
    )
    embedding: EmbeddingConfig = Field(
        ...,
        description="Dense vector embedding configuration.",
    )


# Backward-compat alias for existing Celery task dispatch
CreateVectorStorePayload = IndexCollectionPayload
