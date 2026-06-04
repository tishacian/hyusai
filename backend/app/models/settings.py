"""Application settings model"""
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, JSON, ForeignKey, UniqueConstraint
from app.db.base import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(String(50), primary_key=True, default="default")
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True, index=True)

    default_model = Column(String(100), default="gpt-5")
    default_provider = Column(String(50), default="openai")
    temperature = Column(Float, default=0.3)
    max_tokens = Column(Integer, default=4000)
    top_k = Column(Integer, default=5)
    preferred_agents = Column(JSON, default=list)

    enable_rag = Column(Boolean, default=True)
    enable_reasoning = Column(Boolean, default=True)
    enable_search = Column(Boolean, default=False)

    rag_top_k = Column(Integer, default=5)
    rag_similarity_threshold = Column(Float, default=0.2)
    rag_collection_name = Column(String(100), default="documents")
    rag_use_hybrid_search = Column(Boolean, default=True)
    rag_vector_weight = Column(Float, default=0.7)
    rag_bm25_weight = Column(Float, default=0.3)
    rag_vector_db_type = Column(String(20), default="qdrant")
    rag_chunking_method = Column(String(50), default="recursive_character")
    rag_chunk_size = Column(Integer, default=1000)
    rag_chunk_overlap = Column(Integer, default=200)

    enable_streaming = Column(Boolean, default=True)
    streaming_speed = Column(String(20), default="normal")
    theme = Column(String(20), default="light")
    font_size = Column(String(20), default="medium")
    show_reasoning_traces = Column(Boolean, default=True)
    show_sources = Column(Boolean, default=True)
    auto_expand_reasoning = Column(Boolean, default=False)

    api_url = Column(String(500), default="http://localhost:8000/api/v1")
    api_timeout = Column(Integer, default=30000)
    enable_caching = Column(Boolean, default=True)
    cache_ttl = Column(Integer, default=3600)
    enable_rate_limiting = Column(Boolean, default=True)
    rate_limit_per_minute = Column(Integer, default=60)

    ollama_base_url = Column(String(500), default="http://localhost:11434")
    ollama_num_ctx = Column(Integer, default=32768)
    ollama_rope_scale = Column(Float, nullable=True)
    ollama_rope_alpha = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("id", "workspace_id", name="uq_settings_workspace"),)
