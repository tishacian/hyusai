from typing import Literal

from pydantic import BaseModel, Field


class EmbeddingConfig(BaseModel):
    model_name: str = Field(
        "sentence-transformers/all-mpnet-base-v2",
        examples=[
            "sentence-transformers/all-MiniLM-L6-v2",
            "sentence-transformers/all-MiniLM-L12-v2",
            "sentence-transformers/all-mpnet-base-v2",
        ],
        description=(
            "Sentence-transformers model used to encode text chunks into dense vectors. "
            "Larger models produce higher-quality embeddings at the cost of indexing speed. "
            "Must match the model used at query time."
        ),
    )
    normalization: Literal["l2", "min_max", "z_score", "raw"] = Field(
        "l2",
        description=(
            "Vector normalization applied before storing in Qdrant. "
            "'l2' (unit-norm): standard for cosine similarity — recommended in most cases. "
            "'min_max': scales each dimension to [0, 1] — useful when all dimensions are positive. "
            "'z_score': standardises to zero mean and unit variance — useful for dot-product similarity. "
            "'raw': no normalization — only use if you manage normalization upstream."
        ),
    )
    distance_metric: Literal["cosine", "dot", "euclidean"] = Field(
        "cosine",
        description=(
            "Similarity metric used by Qdrant for nearest-neighbor search. "
            "'cosine': angle-based similarity — invariant to vector magnitude, most common. "
            "'dot': dot product — fast but sensitive to vector scale; pair with 'l2' normalization. "
            "'euclidean': L2 distance — intuitive but slower at scale."
        ),
    )
    source_collection: str | None = Field(
        None,
        description=(
            "Name of an existing collection whose Qdrant points are copied into the new collection "
            "before indexing new documents. Enables incremental collection building. "
            "None creates a fresh collection."
        ),
    )
    batch_size: int | None = Field(
        None,
        ge=1,
        description=(
            "Number of chunks embedded per inference call. "
            "None activates memory-adaptive dynamic batching (recommended). "
            "Set explicitly to control GPU memory usage on constrained hardware."
        ),
    )


# Backward-compat alias
EmbeddingParams = EmbeddingConfig
