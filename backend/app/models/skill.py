"""Canonical Skill model — the typed, certified, atomic operation.

Skills are the building blocks Capabilities compose with. The OmniRAG
engine (chat RAG, evaluation, intelligence batch, sharepoint sync, voice…)
is exposed through this registry as canonical skills (cf.
backend/app/services/skills_registry).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, JSON, String, Text

from app.db.base import Base


class Skill(Base):
    __tablename__ = "skills"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=True, index=True)

    slug = Column(String(160), unique=True, nullable=False, index=True)  # e.g. llm_rag_answer
    version = Column(String(20), default="1")
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    type = Column(String(60), default="generic")  # llm_call | retrieval | analysis | generation | …
    # Product taxonomy for discovery surfaces (palette sections, catalog
    # filters). ``type`` stays the engine-facing contract shape; a single
    # ``type`` legitimately spans several categories and vice versa.
    category = Column(String(40), nullable=True, index=True)

    input_schema = Column(JSON, default=dict)
    output_schema = Column(JSON, default=dict)

    execution = Column(JSON, default=lambda: {"mode": "sync", "timeout_ms": 30000, "retryable": True, "idempotent": True})
    pricing = Column(JSON, default=lambda: {"unit": "per_call", "unit_price": 0.0, "currency": "USD"})

    metrics = Column(JSON, default=dict)  # rolled-up perf metrics from SkillInvocations

    certification_level = Column(String(20), default="basic")  # basic | production | enterprise
    is_seeded = Column(String(1), default="N")
    provider = Column(String(80), nullable=True)               # ollama | azure | openai | internal …

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
