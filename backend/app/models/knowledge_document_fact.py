"""Structured facts extracted from non-tabular Knowledge documents."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text

from app.db.base import Base


class KnowledgeDocumentFact(Base):
    """Workspace-scoped structured evidence for manuals, procedures and guides."""

    __tablename__ = "knowledge_document_facts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    collection_id = Column(String(36), ForeignKey("knowledge_collections.id", ondelete="CASCADE"), nullable=False, index=True)
    collection_slug = Column(String(120), nullable=False, index=True)

    document_id = Column(String(255), nullable=True, index=True)
    document_filename = Column(Text, nullable=True)
    document_type = Column(String(64), nullable=True, index=True)
    source_path = Column(Text, nullable=True)

    semantic_type = Column(String(64), nullable=False, index=True)
    subject = Column(Text, nullable=True)
    predicate = Column(String(128), nullable=True, index=True)
    value_raw = Column(Text, nullable=True)
    value_numeric = Column(Float, nullable=True, index=True)
    unit = Column(String(128), nullable=True, index=True)

    page = Column(Integer, nullable=True, index=True)
    section_path = Column(Text, nullable=True)
    paragraph_index = Column(Integer, nullable=True, index=True)
    table_index = Column(Integer, nullable=True)
    evidence_locator = Column(JSON, nullable=False, default=dict)
    qualifiers = Column(JSON, nullable=False, default=dict)
    semantic_tags = Column(JSON, nullable=False, default=list)
    confidence = Column(Float, nullable=False, default=0.65)
    content = Column(Text, nullable=False, default="")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


Index("ix_knowledge_document_facts_workspace_collection", KnowledgeDocumentFact.workspace_id, KnowledgeDocumentFact.collection_slug)
Index("ix_knowledge_document_facts_collection_type", KnowledgeDocumentFact.collection_id, KnowledgeDocumentFact.semantic_type)
Index("ix_knowledge_document_facts_subject_predicate", KnowledgeDocumentFact.subject, KnowledgeDocumentFact.predicate)
