"""Canonical knowledge collection and worker job ledger."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


COLLECTION_STATUSES = ("created", "queued", "ingesting", "embedding", "ready", "error")
WORKER_JOB_KINDS = (
    "document_ingest_index",
    "vector_reindex",
    "bm25_rebuild",
    "rag_deep_retrieval",
    "sparse_index_rebuild",
    "summary_index_rebuild",
    "qdrant_sparse_reindex",
)
WORKER_JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled")


class KnowledgeCollection(Base):
    """Workspace-scoped RAG collection metadata.

    The vector database remains the source of truth for chunks, while this row
    gives Agentium a tenant-scoped lifecycle and artifact ledger.
    """

    __tablename__ = "knowledge_collections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug = Column(String(120), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String(32), nullable=False, default="created", server_default="created")

    document_names = Column(JSON, nullable=False, default=list)
    vector_collection_name = Column(String(255), nullable=False)
    artifact_prefix = Column(Text, nullable=False)

    embedding_model = Column(String(255), nullable=True)
    chunking_method = Column(String(100), nullable=True)
    chunking_params = Column(JSON, nullable=True)

    document_count = Column(Integer, nullable=False, default=0, server_default="0")
    chunk_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    jobs = relationship(
        "WorkerJob",
        back_populates="collection",
        cascade="all, delete-orphan",
    )
    sources = relationship(
        "KnowledgeCollectionSource",
        back_populates="collection",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_knowledge_collections_workspace_slug"),
        CheckConstraint(
            "status IN ('created', 'queued', 'ingesting', 'embedding', 'ready', 'error')",
            name="ck_knowledge_collections_status",
        ),
        Index("ix_knowledge_collections_workspace_status", "workspace_id", "status"),
    )


class WorkerJob(Base):
    """Persisted status for Celery-backed Agentium work."""

    __tablename__ = "worker_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collection_id = Column(
        String(36),
        ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    kind = Column(String(64), nullable=False)
    celery_task_id = Column(String(255), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="queued", server_default="queued")
    progress = Column(Integer, nullable=False, default=0, server_default="0")
    error = Column(Text, nullable=True)
    result = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    collection = relationship("KnowledgeCollection", back_populates="jobs")

    __table_args__ = (
        CheckConstraint(
            "kind IN ('document_ingest_index', 'vector_reindex', 'bm25_rebuild', 'rag_deep_retrieval', 'sparse_index_rebuild', 'summary_index_rebuild', 'qdrant_sparse_reindex')",
            name="ck_worker_jobs_kind",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_worker_jobs_status",
        ),
        Index("ix_worker_jobs_workspace_status", "workspace_id", "status"),
    )


SOURCE_STATUSES = ("queued", "ingesting", "indexed", "ready", "error", "deleted")


class KnowledgeCollectionSource(Base):
    """Per-source inventory for a Knowledge collection.

    ``KnowledgeCollection.document_names`` is kept for backward compatibility,
    but this ledger is the authoritative place for source cardinality,
    typology, size and indexing status.
    """

    __tablename__ = "knowledge_collection_sources"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collection_id = Column(
        String(36),
        ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = Column(Text, nullable=False)
    normalized_name = Column(String(512), nullable=False)
    source_kind = Column(String(80), nullable=False, default="document", server_default="document")
    extension = Column(String(32), nullable=False, default="", server_default="")
    mime_type = Column(String(160), nullable=False, default="", server_default="")
    origin = Column(String(80), nullable=False, default="upload", server_default="upload")
    size_bytes = Column(Integer, nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(String(32), nullable=False, default="queued", server_default="queued")
    source_metadata = Column(JSON, nullable=False, default=dict)
    last_error = Column(Text, nullable=True)
    indexed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    collection = relationship("KnowledgeCollection", back_populates="sources")

    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "normalized_name",
            name="uq_knowledge_collection_sources_collection_name",
        ),
        CheckConstraint(
            "status IN ('queued', 'ingesting', 'indexed', 'ready', 'error', 'deleted', 'deduplicated')",
            name="ck_knowledge_collection_sources_status",
        ),
        Index("ix_knowledge_collection_sources_workspace_collection", "workspace_id", "collection_id"),
        Index("ix_knowledge_collection_sources_kind", "workspace_id", "source_kind"),
    )
