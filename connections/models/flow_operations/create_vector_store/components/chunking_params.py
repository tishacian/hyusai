from typing import Annotated, Literal

from pydantic import BaseModel, Field, PositiveInt


class FixedChunkingParams(BaseModel):
    """Parameters for fixed-size text chunking."""

    method: Literal["fixed"]
    generation_model_name: str = Field(
        description="Name of the LLM model that will be used to determine "
        "the maximum chunk length.",
    )
    max_chunk_length: PositiveInt | None = Field(
        None,
        description="Maximum number of characters per chunk. "
        "If not provided, defaults to the model's maximum context length.",
    )


class RecursiveCharacterChunkingParams(BaseModel):
    """Parameters for recursive character-based chunking."""

    method: Literal["recursive_character"]
    generation_model_name: str = Field(
        description="Name of the LLM model that will be used to determine "
        "the maximum chunk length.",
    )
    max_chunk_length: PositiveInt | None = Field(
        None,
        description="Maximum number of characters per chunk before the text is split recursively.",
    )
    overlap_size: PositiveInt | None = Field(
        None, description="Number of characters overlapping between consecutive chunks."
    )


class SemanticChunkingParams(BaseModel):
    """Parameters for semantic (embedding-based) chunking."""

    method: Literal["semantic"]
    cluster_selection_method: Literal["elbow", "silhouette", "gap"] | None = Field(
        None,
        description="Statistical method used to determine the optimal number of clusters.",
    )
    max_k: PositiveInt | None = Field(
        None,
        description="Maximum number of clusters (k) to evaluate when grouping semantically similar sentences.",
    )


class TokenBasedChunkingParams(BaseModel):
    """Parameters for token-based (LLM) chunking."""

    method: Literal["token_based"]
    generation_model_name: str = Field(
        description="Name of the LLM model that will be used to determine "
        "the tokenizer model.",
    )
    max_tokens_per_chunk: PositiveInt | None = Field(
        None,
        description="Maximum number of tokens allowed in each chunk. "
        "Usually matches the model's context window size (e.g., 512 or 1024).",
    )


class HierarchicalChunkingParams(BaseModel):
    """Parameters for hierarchical paragraph/sentence chunking."""

    method: Literal["hierarchical"]
    max_paragraph_length: PositiveInt | None = Field(
        None,
        description="Maximum paragraph length before splitting into smaller chunks.",
    )
    max_sentence_length: PositiveInt | None = Field(
        None, description="Maximum sentence length within a paragraph chunk."
    )


class ModelBasedChunkingParams(BaseModel):
    """Parameters for model-driven chunk boundary detection."""

    method: Literal["model_based"]
    generation_model_name: str = Field(
        description="Name of the LLM model that will be used to determine "
        "the tokenizer model.",
    )
    max_tokens_per_chunk: PositiveInt | None = Field(
        None, description="Maximum number of tokens to include in each chunk."
    )
    boundary_detection_model_name: str | None = Field(
        None,
        description="Name of the model used to detect chunk boundaries.",
    )
    boundary_confidence_threshold: Annotated[float, Field(gt=0.0, lt=1.0)] | None = (
        Field(
            None,
            description="Threshold for the model’s confidence when deciding a chunk boundary. "
            "Higher values produce fewer, larger chunks.",
        )
    )


class SentenceBoundaryChunkingParams(BaseModel):
    """Parameters for sentence boundary detection."""

    method: Literal["sentence_boundary"]


ChunkingParams = Annotated[
    FixedChunkingParams
    | RecursiveCharacterChunkingParams
    | SemanticChunkingParams
    | TokenBasedChunkingParams
    | HierarchicalChunkingParams
    | ModelBasedChunkingParams
    | SentenceBoundaryChunkingParams,
    Field(discriminator="method"),
]
