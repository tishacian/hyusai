"""SystemBinding — a stable key locked to one published Flow ingress.

An Experience action (`nawa.password_reset`, `expenses.submit`) points at a
published System version and the ingress contract it was bound against. The
System may republish; the binding does not follow until an operator updates it.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)

from app.db.base import Base


CONFIRMATION_POLICIES = ("direct-safe", "confirm", "hitl")
ON_UNAVAILABLE_POLICIES = ("empty", "unavailable", "admin-repair")


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class SystemBinding(Base):
    __tablename__ = "system_bindings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    binding_key = Column(String(120), nullable=False)
    system_id = Column(
        String(36),
        ForeignKey("systems.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    published_flow_version_id = Column(String(36), nullable=False)
    flow_sha256 = Column(String(64), nullable=False)
    ingress_id = Column(String(160), nullable=False)
    input_schema_sha256 = Column(String(64), nullable=False)
    output_schema_sha256 = Column(String(64), nullable=True)
    confirmation_policy = Column(String(32), nullable=False, default="confirm")
    on_unavailable = Column(String(32), nullable=False, default="unavailable")
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "binding_key",
            name="uq_system_bindings_workspace_key",
        ),
        CheckConstraint(
            _enum_check("confirmation_policy", CONFIRMATION_POLICIES),
            name="ck_system_bindings_confirmation_policy",
        ),
        CheckConstraint(
            _enum_check("on_unavailable", ON_UNAVAILABLE_POLICIES),
            name="ck_system_bindings_on_unavailable",
        ),
    )
