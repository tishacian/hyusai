from typing import Literal

from pydantic import BaseModel, Field


class RetrievalConfig(BaseModel):
    strategy: Literal["HAH", "HAHCOMPOSITE", "NAIVE"] = Field(
        "HAHCOMPOSITE",
        description=(
            "Retrieval strategy used to fetch relevant document chunks. "
            "NAIVE: direct dense vector similarity search — fast, no re-ranking. "
            "HAH (Hybrid Adaptive Hybrid): combines BM25 keyword search with dense vector search, "
            "then applies reasoning-aware re-ranking. "
            "HAHCOMPOSITE: HAH with multi-pass retrieval and tiered result caching for "
            "high-throughput or repeated query patterns."
        ),
    )
    embedding_model_name: str = Field(
        "sentence-transformers/all-mpnet-base-v2",
        description=(
            "Sentence-transformers model used to encode the query into a dense vector. "
            "Must match the model used at indexing time — mismatches produce irrelevant results."
        ),
    )
    top_k: int = Field(
        5,
        ge=1,
        le=50,
        description=(
            "Number of document chunks to retrieve from the vector store. "
            "Higher values provide broader context but increase LLM token usage and latency. "
            "Automatically overridden per-query when dynamic_k=True."
        ),
    )
    dynamic_k: bool = Field(
        True,
        description=(
            "Scale top_k automatically based on estimated query complexity. "
            "Multi-part or comparative questions retrieve more chunks; "
            "simple factual lookups retrieve fewer. "
            "When enabled, top_k acts as the upper bound."
        ),
    )
    cache_size: int = Field(
        1000,
        ge=0,
        description=(
            "Maximum number of query results to keep in the LRU retrieval cache. "
            "0 disables caching. Caching is only active for HAH and HAHCOMPOSITE strategies. "
            "Reduces latency for repeated or similar queries in the same session."
        ),
    )
