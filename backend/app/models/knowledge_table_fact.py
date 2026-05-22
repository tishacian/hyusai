"""Structured facts extracted from tabular Knowledge documents."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text

from app.db.base import Base


class KnowledgeTableFact(Base):
    """Workspace-scoped structured evidence for spreadsheet/CSV analysis."""

    __tablename__ = "knowledge_table_facts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    collection_id = Column(String(36), ForeignKey("knowledge_collections.id", ondelete="CASCADE"), nullable=False, index=True)
    collection_slug = Column(String(120), nullable=False, index=True)

    document_id = Column(String(255), nullable=True, index=True)
    document_filename = Column(Text, nullable=True)
    document_type = Column(String(64), nullable=True)
    source_path = Column(Text, nullable=True)

    sheet_name = Column(String(255), nullable=True, index=True)
    table_region_id = Column(String(255), nullable=True, index=True)
    semantic_type = Column(String(64), nullable=False, index=True)

    row_index = Column(Integer, nullable=True, index=True)
    column_index = Column(Integer, nullable=True)
    cell_ref = Column(String(64), nullable=True, index=True)
    cell_range = Column(String(128), nullable=True)

    row_label = Column(Text, nullable=True)
    column_header = Column(Text, nullable=True)
    subject = Column(Text, nullable=True)
    measure = Column(Text, nullable=True)
    value_raw = Column(Text, nullable=True)
    value_numeric = Column(Float, nullable=True, index=True)
    unit = Column(String(128), nullable=True, index=True)

    qualifiers = Column(JSON, nullable=False, default=dict)
    semantic_tags = Column(JSON, nullable=False, default=list)
    confidence = Column(Float, nullable=False, default=0.7)
    content = Column(Text, nullable=False, default="")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


Index("ix_knowledge_table_facts_workspace_collection", KnowledgeTableFact.workspace_id, KnowledgeTableFact.collection_slug)
Index("ix_knowledge_table_facts_collection_type", KnowledgeTableFact.collection_id, KnowledgeTableFact.semantic_type)
Index("ix_knowledge_table_facts_measure_subject", KnowledgeTableFact.measure, KnowledgeTableFact.subject)
