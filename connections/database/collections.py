from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy
from sqlalchemy import JSON, String, Text, func
from sqlalchemy import DateTime as SQLADateTime
from sqlalchemy.orm import Mapped, Session, mapped_column

from connections.database.base import Base
from connections.database.utils import session_manager_decorator

CollectionStatus = str
# Allowed values: "created" | "ingesting" | "embedding" | "ready" | "error"


class Collection(Base):
    __tablename__ = "collections"

    # Identity
    uuid: Mapped[str] = mapped_column(
        String(36),
        default=lambda: str(uuid4()),
        primary_key=True,
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Lifecycle
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="created")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        SQLADateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        SQLADateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Ownership
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)

    # Document tracking
    document_names: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )

    # Embedding config — populated when create_vector_store runs
    embedding_model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chunking_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    chunking_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    @property
    def nb_docs(self) -> int:
        return len(self.document_names or [])

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @classmethod
    @session_manager_decorator
    def get_all(
        cls, status: CollectionStatus | None = None, *, session: Session = None
    ) -> list["Collection"]:
        """Return all collections sorted by creation time descending.

        Pass status="ready" to get only fully embedded collections
        (equivalent to the old only_embedded=True filter).
        """
        stmt = sqlalchemy.select(cls)
        if status is not None:
            stmt = stmt.where(cls.status == status)
        stmt = stmt.order_by(cls.created_at.desc())
        return session.scalars(stmt).all()

    @classmethod
    @session_manager_decorator
    def get_by_uuid(
        cls, uuid: UUID | str, *, session: Session = None
    ) -> "Collection | None":
        """Return a Collection by UUID or None if not found."""
        stmt = sqlalchemy.select(cls).where(cls.uuid == str(uuid))
        return session.execute(stmt).scalar_one_or_none()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    @classmethod
    @session_manager_decorator
    def create(
        cls,
        name: str,
        created_by: str,
        description: str = "",
        document_names: list[str] | None = None,
        *,
        session: Session = None,
    ) -> "Collection":
        """Create and persist a new collection."""
        col = cls(
            name=name,
            created_by=created_by,
            description=description,
            document_names=document_names or [],
        )
        session.add(col)
        return col

    @classmethod
    @session_manager_decorator
    def update(
        cls,
        uuid: UUID | str,
        *,
        name: str | None = None,
        description: str | None = None,
        status: CollectionStatus | None = None,
        document_names: list[str] | None = None,
        embedding_model_name: str | None = None,
        chunking_method: str | None = None,
        chunking_params: dict | None = None,
        session: Session = None,
    ) -> "Collection | None":
        """Patch any subset of mutable fields. Returns the updated instance or None if not found."""
        stmt = sqlalchemy.select(cls).where(cls.uuid == str(uuid))
        col = session.execute(stmt).scalar_one_or_none()
        if col is None:
            return None
        updates = {
            "name": name,
            "description": description,
            "status": status,
            "document_names": document_names,
            "embedding_model_name": embedding_model_name,
            "chunking_method": chunking_method,
            "chunking_params": chunking_params,
        }
        for field, value in updates.items():
            if value is not None:
                setattr(col, field, value)
        return col

    @classmethod
    @session_manager_decorator
    def delete(cls, uuid: UUID | str, *, session: Session = None) -> bool:
        """Delete a collection by UUID. Returns True if deleted, False if not found."""
        stmt = sqlalchemy.select(cls).where(cls.uuid == str(uuid))
        col = session.execute(stmt).scalar_one_or_none()
        if not col:
            return False
        session.delete(col)
        return True
