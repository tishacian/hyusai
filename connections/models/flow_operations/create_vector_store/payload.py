from uuid import UUID

from pydantic import BaseModel

from .components.chunking_params import ChunkingParams
from .components.embedding_params import EmbeddingParams


class CreateVectorStorePayload(BaseModel):
    knowledge_base_uuid: UUID
    chunking_params: ChunkingParams
    embedding_params: EmbeddingParams
