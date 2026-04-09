from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EmbeddingParams(BaseModel):
    old_vector_store_uuid: UUID | None = Field(
        None,
        description=(
            "Optional UUID of an existing vector store whose contents will be included "
            "in the new vector store along with the new documents. "
            "The old vector store itself will not be modified."
        ),
    )
    embedding_model_name: str = Field(
        "sentence-transformers/all-mpnet-base-v2",
        examples=[
            "sentence-transformers/all-MiniLM-L6-v2",
            "sentence-transformers/all-MiniLM-L12-v2",
            "sentence-transformers/all-mpnet-base-v2",
        ],
        description="The name of the embedding model to use for generating vector "
        "representations of documents.",
    )
    normalization_strategy: Literal["l2", "min_max", "z_score", "raw"] = Field(
        "l2",
        description="The strategy used to normalize the embeddings before storing them.",
    )
