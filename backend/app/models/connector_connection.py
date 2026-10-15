"""Workspace connections and personal grants. Credentials live only in the registry."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)

from app.db.base import Base


def _id():
    return str(uuid4())


class ConnectorConnection(Base):
    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_connections_workspace_name"),
        UniqueConstraint("workspace_id", "legacy_source", name="uq_connections_legacy_source"),
        UniqueConstraint("workspace_id", "id", name="uq_connections_tenant_id"),
        CheckConstraint("access IN ('read','read_write')", name="ck_connections_access"),
        CheckConstraint("revision > 0 AND profile_version > 0", name="ck_connections_revision"),
    )
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(120), nullable=False)
    profile_key = Column(String(80), nullable=False)
    profile_version = Column(Integer, nullable=False)
    values = Column(JSON, nullable=False, default=dict)
    secret_refs = Column(JSON, nullable=False, default=dict)
    access = Column(String(16), nullable=False, default="read")
    allowed_schemas = Column(JSON, nullable=False, default=list)
    allowed_tables = Column(JSON, nullable=False, default=list)
    revision = Column(Integer, nullable=False, default=1)
    legacy_source = Column(String(120), nullable=True)
    last_test = Column(JSON, nullable=True)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    disabled_at = Column(DateTime, nullable=True)


class ConnectorGrant(Base):
    __tablename__ = "connector_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_connector_grants_tenant_id"),
        UniqueConstraint(
            "connection_id", "owner_user_id", name="uq_connector_grants_connection_user"
        ),
    )
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(String(36), nullable=False, index=True)
    connection_id = Column(String(36), nullable=False)
    owner_user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scopes = Column(JSON, nullable=False, default=list)
    token_refs = Column(JSON, nullable=False, default=dict)
    granted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(255), nullable=True)


class ConnectorDelegation(Base):
    __tablename__ = "connector_delegations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "grant_id"],
            ["connector_grants.workspace_id", "connector_grants.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("grant_id", "system_version_id", name="uq_connector_delegations_version"),
    )
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(String(36), nullable=False, index=True)
    grant_id = Column(String(36), nullable=False)
    system_id = Column(String(36), ForeignKey("systems.id", ondelete="CASCADE"), nullable=False)
    system_version_id = Column(
        String(36), ForeignKey("system_versions.id", ondelete="CASCADE"), nullable=False
    )
    created_by = Column(String(36), nullable=False)
    approved_by = Column(String(36), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
