from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy
from sqlalchemy import JSON, Integer, String, Text, func
from sqlalchemy import DateTime as SQLADateTime
from sqlalchemy.orm import Mapped, Session, mapped_column

from connections.database.base import Base
from connections.database.utils import session_manager_decorator
from connections.models.flow_operations.create_vector_store.components.chunking_params import (
    ChunkingParams,
)
from connections.models.flow_operations.create_vector_store.components.embedding_params import (
    EmbeddingParams,
)


class KnowledgeBases(Base):
    __tablename__ = "knowledge_bases"

    uuid: Mapped[str] = mapped_column(
        String(36),
        default=lambda: str(uuid4()),
        primary_key=True,
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        SQLADateTime,
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    document_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    is_embedded: Mapped[bool] = mapped_column(nullable=False, default=False)
    # only set by create_vector_store task TODO: use it
    chunking_params: Mapped[dict] = mapped_column(JSON, nullable=True)
    embedding_params: Mapped[dict] = mapped_column(JSON, nullable=True)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=True)

    @classmethod
    @session_manager_decorator
    def get_all(
        cls, only_embedded: bool = False, *, session: Session = None
    ) -> list["KnowledgeBases"]:
        """Return all knowledge bases sorted by creation time in descending order."""
        stmt = sqlalchemy.select(cls)
        if only_embedded:
            stmt = stmt.where(cls.is_embedded)
        stmt = stmt.order_by(cls.created_at.desc())
        return session.scalars(stmt).all()

    @classmethod
    @session_manager_decorator
    def get_by_uuid(
        cls, uuid: UUID, *, session: Session = None
    ) -> "KnowledgeBases | None":
        """Return a KnowledgeBases instance by UUID or None if not found"""
        stmt = sqlalchemy.select(cls).where(cls.uuid == str(uuid))
        return session.execute(stmt).scalar_one_or_none()

    @classmethod
    @session_manager_decorator
    def add(
        cls,
        name: str,
        created_by: str,
        document_names: list[str],
        description: str = "",
        *,
        session: Session = None,
    ) -> "KnowledgeBases":
        """Create and persist a new knowledge base"""
        kb = cls(
            name=name,
            created_by=created_by,
            description=description,
            document_names=document_names,
        )
        session.add(kb)
        return kb

    @classmethod
    @session_manager_decorator
    def delete(cls, uuid: UUID, *, session: Session = None) -> bool:
        """Delete a knowledge base by UUID. Returns True if deleted, False if not found"""
        stmt = sqlalchemy.select(cls).where(cls.uuid == str(uuid))
        kb = session.execute(stmt).scalar_one_or_none()
        if not kb:
            return False
        session.delete(kb)
        return True

    @classmethod
    @session_manager_decorator
    def set_embedding_info(
        cls,
        uuid: UUID,
        chunking_params: ChunkingParams,
        embedding_params: EmbeddingParams,
        embedding_dimension: int,
        *,
        session: Session = None,
    ) -> None:
        """Update the embedding information of a knowledge base."""
        stmt = (
            sqlalchemy.update(cls)
            .where(cls.uuid == str(uuid))
            .values(
                is_embedded=True,
                chunking_params=chunking_params.model_dump(),
                embedding_params=embedding_params.model_dump(),
                embedding_dimension=embedding_dimension,
            )
        )
        session.execute(stmt)
